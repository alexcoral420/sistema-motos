"""
API externa (/api, la consume n8n): llave con rotación, log por petición
y registro de intenciones con dedup y topes.

Nada toca Supabase: los servicios y el repositorio se reemplazan con
monkeypatch, y las intenciones viven en una lista en memoria.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.db import repositorios
from app.seguridad.limites import limiter
from app.seguridad.logging_config import obtener_logger_api
from app.seguridad.validadores import ErrorValidacion
from app.servicios import catalogo, inventario

LLAVE = "llave-principal-de-prueba-0123456789"
LLAVE_VIEJA = "llave-anterior-de-prueba-9876543210"
CLAVE = "secreto-de-prueba"
AHORA = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def app():
    app = create_app()
    # create_app conecta el limiter GLOBAL; desde ahí sus decoradores
    # limitarían también las apps mínimas de otros archivos de pruebas
    # (429 inesperados). Se deja apagado para el resto de la corrida.
    limiter.enabled = False
    return app


@pytest.fixture
def cliente(app, monkeypatch):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY", LLAVE)
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY_ANTERIOR", None)
    monkeypatch.setitem(app.config, "SECRET_KEY", CLAVE)
    # El rate limit en memoria no es lo que se prueba aquí y sus contadores
    # se compartirían entre pruebas.
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(inventario, "obtener_moto",
                        lambda moto_id: {"id": moto_id, "sede_id": 1} if moto_id < 900 else None)
    monkeypatch.setattr(repositorios, "obtener_fotos_moto", lambda moto_id: [])
    monkeypatch.setattr(catalogo, "buscar_motos", lambda args: {
        "motos": [], "total_motos": 0, "pagina": 1, "total_paginas": 0})
    return app.test_client()


@pytest.fixture
def registro(caplog):
    caplog.set_level(logging.INFO, logger="auditoria.api")
    return caplog


def _bearer(llave):
    return {"Authorization": f"Bearer {llave}"}


def _lineas_api(registro):
    return [r for r in registro.records if r.name == "auditoria.api"]


# ---------------------------------------------------------------- llave

def test_llave_principal_entra(cliente):
    assert cliente.get("/api/motos/5", headers=_bearer(LLAVE)).status_code == 200


def test_sin_cabecera_es_401(cliente):
    assert cliente.get("/api/motos/5").status_code == 401


def test_llave_equivocada_es_401(cliente):
    assert cliente.get("/api/motos/5", headers=_bearer("otra")).status_code == 401


def test_llave_con_caracteres_no_ascii_es_401_y_no_500(cliente):
    respuesta = cliente.get("/api/motos/5", headers={"Authorization": "Bearer ñandú"})
    assert respuesta.status_code == 401


def test_llave_anterior_no_vale_si_no_esta_configurada(cliente):
    assert cliente.get("/api/motos/5", headers=_bearer(LLAVE_VIEJA)).status_code == 401


def test_durante_la_rotacion_valen_las_dos(cliente, app, monkeypatch):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY_ANTERIOR", LLAVE_VIEJA)
    assert cliente.get("/api/motos/5", headers=_bearer(LLAVE)).status_code == 200
    assert cliente.get("/api/motos/5", headers=_bearer(LLAVE_VIEJA)).status_code == 200
    assert cliente.get("/api/motos/5", headers=_bearer("otra")).status_code == 401


@pytest.mark.parametrize("principal", [None, ""])
def test_sin_llave_principal_es_503_aunque_exista_la_anterior(cliente, app, monkeypatch, principal):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY", principal)
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY_ANTERIOR", LLAVE_VIEJA)
    assert cliente.get("/api/motos/5", headers=_bearer(LLAVE_VIEJA)).status_code == 503
    assert cliente.get("/api/motos/5").status_code == 503


def test_una_llave_anterior_vacia_no_abre_la_puerta(cliente, app, monkeypatch):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY_ANTERIOR", "")
    assert cliente.get("/api/motos/5", headers={"Authorization": "Bearer "}).status_code == 401


# ------------------------------------------------------------------ log

def test_log_de_un_200(cliente, registro):
    cliente.get("/api/motos/5", headers=_bearer(LLAVE))
    (linea,) = _lineas_api(registro)
    assert linea.levelno == logging.INFO
    assert linea.getMessage() == \
        "API | GET /api/motos/<int:moto_id> | 200 | ip=127.0.0.1 | consumidor=n8n"


def test_log_de_la_llave_anterior(cliente, registro, app, monkeypatch):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY_ANTERIOR", LLAVE_VIEJA)
    cliente.get("/api/motos/5", headers=_bearer(LLAVE_VIEJA))
    (linea,) = _lineas_api(registro)
    assert linea.getMessage().endswith("| 200 | ip=127.0.0.1 | consumidor=n8n(anterior)")


@pytest.mark.parametrize("cabeceras, consumidor", [
    ({}, "sin_llave"),
    ({"Authorization": "Bearer llave-que-no-es"}, "llave_invalida"),
])
def test_log_de_un_401(cliente, registro, cabeceras, consumidor):
    cliente.get("/api/motos/buscar", headers=cabeceras)
    (linea,) = _lineas_api(registro)
    assert linea.levelno == logging.WARNING
    assert linea.getMessage() == \
        f"API | GET /api/motos/buscar | 401 | ip=127.0.0.1 | consumidor={consumidor}"


def test_log_de_un_503(cliente, registro, app, monkeypatch):
    monkeypatch.setitem(app.config, "API_WEBHOOK_KEY", None)
    cliente.post("/api/intenciones", json={"moto_id": 5}, headers=_bearer(LLAVE))
    (linea,) = _lineas_api(registro)
    assert linea.levelno == logging.ERROR
    assert linea.getMessage() == \
        "API | POST /api/intenciones | 503 | ip=127.0.0.1 | consumidor=sin_configurar"


def test_log_de_una_ruta_publica(cliente, registro, monkeypatch):
    # La validación del avalúo lee los modelos de la base: se reemplaza.
    monkeypatch.setattr(repositorios, "pares_marca_modelo", lambda: [])
    cliente.get("/api/avaluo")          # sin parámetros: 400
    (linea,) = _lineas_api(registro)
    assert linea.getMessage().endswith("| consumidor=publico")
    assert "GET /api/avaluo | 400" in linea.getMessage()


def test_el_log_no_lleva_query_string_cuerpo_ni_llave(cliente, registro, monkeypatch):
    _base_de_intenciones(monkeypatch)
    cliente.get("/api/motos/buscar?q=ABC12D&marca=YAMAHA", headers=_bearer(LLAVE))
    cliente.get("/api/motos/buscar?q=ABC12D", headers=_bearer("llave-mala-secreta"))
    cliente.post("/api/intenciones", json={"moto_id": 5, "origen": "573001234567"},
                 headers=_bearer(LLAVE))
    texto = registro.text
    assert len(_lineas_api(registro)) == 3
    for prohibido in ("ABC12D", "YAMAHA", "573001234567", LLAVE, LLAVE[:8],
                      "llave-mala-secreta", "Bearer"):
        assert prohibido not in texto


def test_el_log_de_la_api_se_guarda_aunque_auditoria_este_en_warning():
    """Producción: 'auditoria' en WARNING. Las líneas INFO de la API deben
    llegar igual a sus destinos (los handlers del padre)."""
    recibidos = []

    class Destino(logging.Handler):
        def emit(self, record):
            recibidos.append(record.getMessage())

    padre = logging.getLogger("auditoria")
    nivel_previo = padre.level
    destino = Destino()
    padre.addHandler(destino)
    padre.setLevel(logging.WARNING)
    try:
        padre.info("ruido que en producción no se guarda")
        obtener_logger_api().info("API | GET /api/x | 200")
    finally:
        padre.removeHandler(destino)
        padre.setLevel(nivel_previo)
    assert recibidos == ["API | GET /api/x | 200"]


# -------------------------------------------------- detalle con galería

BUCKET = "https://proyecto.supabase.co/storage/v1/object/public/motos/"


def _moto_con_fotos(monkeypatch, galeria):
    """Una moto con portada y la galería dada (ya en el orden del
    repositorio). Devuelve la lista de ids por los que se pidió galería."""
    pedidas = []

    def fotos(moto_id):
        pedidas.append(moto_id)
        return galeria

    monkeypatch.setattr(inventario, "obtener_moto", lambda moto_id: {
        "id": moto_id, "sede_id": 1, "marca": "YAMAHA",
        "foto_url": BUCKET + "portada.webp", "foto_path": "portada.webp",
    } if moto_id < 900 else None)
    monkeypatch.setattr(repositorios, "obtener_fotos_moto", fotos)
    return pedidas


def _foto(id, nombre, orden):
    return {"id": id, "created_at": "2026-11-01T10:00:00+00:00", "moto_id": 5,
            "foto_url": BUCKET + nombre if nombre else None,
            "foto_path": nombre, "orden": orden}


def test_detalle_devuelve_portada_y_galeria_en_orden(cliente, monkeypatch):
    # 'orden' repetido en la base (0, 0, 3): la posición sale 1, 2, 3.
    pedidas = _moto_con_fotos(monkeypatch, [
        _foto(11, "galeria/a.webp", 0), _foto(12, "galeria/b.webp", 0),
        _foto(10, "galeria/c.webp", 3)])
    respuesta = cliente.get("/api/motos/5", headers=_bearer(LLAVE))
    assert respuesta.status_code == 200
    moto = respuesta.get_json()["moto"]
    assert moto["foto_url"] == BUCKET + "portada.webp"
    assert moto["marca"] == "YAMAHA"
    assert moto["fotos"] == [
        {"url": BUCKET + "galeria/a.webp", "orden": 1},
        {"url": BUCKET + "galeria/b.webp", "orden": 2},
        {"url": BUCKET + "galeria/c.webp", "orden": 3},
    ]
    assert pedidas == [5]


def test_detalle_de_la_galeria_solo_salen_url_y_orden(cliente, monkeypatch):
    _moto_con_fotos(monkeypatch, [_foto(11, "galeria/a.webp", 0)])
    respuesta = cliente.get("/api/motos/5", headers=_bearer(LLAVE))
    (foto,) = respuesta.get_json()["moto"]["fotos"]
    assert set(foto) == {"url", "orden"}


def test_detalle_sin_galeria_devuelve_lista_vacia(cliente, monkeypatch):
    _moto_con_fotos(monkeypatch, [])
    moto = cliente.get("/api/motos/5", headers=_bearer(LLAVE)).get_json()["moto"]
    assert moto["fotos"] == []
    assert moto["foto_url"] == BUCKET + "portada.webp"


def test_detalle_salta_una_foto_sin_url(cliente, monkeypatch):
    _moto_con_fotos(monkeypatch, [_foto(11, None, 0), _foto(12, "galeria/b.webp", 1)])
    moto = cliente.get("/api/motos/5", headers=_bearer(LLAVE)).get_json()["moto"]
    assert moto["fotos"] == [{"url": BUCKET + "galeria/b.webp", "orden": 1}]


def test_detalle_404_no_consulta_la_galeria(cliente, monkeypatch):
    pedidas = _moto_con_fotos(monkeypatch, [_foto(11, "galeria/a.webp", 0)])
    respuesta = cliente.get("/api/motos/999", headers=_bearer(LLAVE))
    assert respuesta.status_code == 404
    assert pedidas == []


def test_detalle_sin_llave_no_consulta_la_galeria(cliente, monkeypatch):
    pedidas = _moto_con_fotos(monkeypatch, [_foto(11, "galeria/a.webp", 0)])
    assert cliente.get("/api/motos/5").status_code == 401
    assert pedidas == []


# ----------------------------------------------------------- intenciones

def _base_de_intenciones(monkeypatch, filas=None):
    """Reemplaza el repositorio por una lista en memoria y la devuelve."""
    filas = filas if filas is not None else []

    def existe(moto_id, sesion_id, desde):
        return any(f["moto_id"] == moto_id and f["sesion_id"] == sesion_id
                   and f["created_at"] >= desde for f in filas)

    def contar(prefijo, desde, moto_id=None):
        return sum(1 for f in filas
                   if (f["sesion_id"] or "").startswith(prefijo) and f["created_at"] >= desde
                   and (moto_id is None or f["moto_id"] == moto_id))

    def registrar(moto_id, sede_id, sesion_id=None):
        filas.append({"moto_id": moto_id, "sede_id": sede_id, "sesion_id": sesion_id,
                      "created_at": _reloj["ahora"].isoformat()})

    monkeypatch.setattr(repositorios, "existe_intencion_desde", existe)
    monkeypatch.setattr(repositorios, "contar_intenciones_por_prefijo", contar)
    monkeypatch.setattr(repositorios, "registrar_intencion", registrar)
    monkeypatch.setattr(inventario, "obtener_moto",
                        lambda moto_id: {"id": moto_id, "sede_id": 1} if moto_id < 900 else None)
    _reloj["ahora"] = AHORA
    return filas


_reloj = {"ahora": AHORA}


def _registrar(moto_id, origen=None, dentro_de=timedelta(0)):
    _reloj["ahora"] = AHORA + dentro_de
    return inventario.registrar_intencion_api(moto_id, origen, CLAVE, ahora=_reloj["ahora"])


def test_intencion_nueva_se_registra_con_la_sede_de_la_moto(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    assert _registrar(5, "conv-1") == inventario.INTENCION_REGISTRADA
    assert len(filas) == 1 and filas[0]["moto_id"] == 5 and filas[0]["sede_id"] == 1


def test_el_origen_no_se_guarda_en_claro(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    _registrar(5, "573001234567")
    sesion = filas[0]["sesion_id"]
    assert sesion.startswith("api:") and len(sesion) == 4 + 32
    assert "573001234567" not in sesion
    # Determinista (si no, no habría dedup) y dependiente de la clave.
    assert sesion == inventario.sesion_de_origen(" 573001234567 ", CLAVE)
    assert sesion != inventario.sesion_de_origen("573001234567", "otra-clave")
    assert sesion != inventario.sesion_de_origen("573001234568", CLAVE)


def test_dedup_con_origen_dura_24_horas(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    assert _registrar(5, "conv-1") == inventario.INTENCION_REGISTRADA
    assert _registrar(5, "conv-1", timedelta(hours=23, minutes=59)) == inventario.INTENCION_DUPLICADA
    assert len(filas) == 1
    assert _registrar(5, "conv-1", timedelta(hours=24, minutes=1)) == inventario.INTENCION_REGISTRADA
    assert len(filas) == 2


def test_dedup_con_origen_es_por_moto_y_por_origen(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    _registrar(5, "conv-1")
    assert _registrar(6, "conv-1") == inventario.INTENCION_REGISTRADA      # otra moto
    assert _registrar(5, "conv-2") == inventario.INTENCION_REGISTRADA      # otra persona
    assert len(filas) == 3


def test_dedup_sin_origen_dura_10_minutos(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    assert _registrar(5) == inventario.INTENCION_REGISTRADA
    assert filas[0]["sesion_id"] == "api:anon"
    assert _registrar(5, dentro_de=timedelta(minutes=9)) == inventario.INTENCION_DUPLICADA
    assert _registrar(5, "   ", timedelta(minutes=9)) == inventario.INTENCION_DUPLICADA  # vacío = sin origen
    assert _registrar(6, dentro_de=timedelta(minutes=9)) == inventario.INTENCION_REGISTRADA
    assert _registrar(5, dentro_de=timedelta(minutes=11)) == inventario.INTENCION_REGISTRADA
    assert len(filas) == 3


def test_tope_por_moto(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    for i in range(inventario.TOPE_INTENCIONES_API_POR_MOTO):
        assert _registrar(5, f"conv-{i}") == inventario.INTENCION_REGISTRADA
    with pytest.raises(inventario.TopeIntencionesSuperado) as e:
        _registrar(5, "conv-nueva")
    assert e.value.alcance == "moto"
    assert len(filas) == inventario.TOPE_INTENCIONES_API_POR_MOTO
    # Otra moto no está topada, y un duplicado sigue respondiendo duplicado.
    assert _registrar(6, "conv-nueva") == inventario.INTENCION_REGISTRADA
    assert _registrar(5, "conv-0") == inventario.INTENCION_DUPLICADA
    # Pasadas 24 h el tope se libera.
    assert _registrar(5, "conv-nueva", timedelta(hours=24, minutes=1)) == inventario.INTENCION_REGISTRADA


def test_tope_global(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    for i in range(inventario.TOPE_INTENCIONES_API_GLOBAL):
        assert _registrar(1 + i % 100, f"conv-{i}") == inventario.INTENCION_REGISTRADA
    with pytest.raises(inventario.TopeIntencionesSuperado) as e:
        _registrar(500, "conv-nueva")
    assert e.value.alcance == "global"
    assert len(filas) == inventario.TOPE_INTENCIONES_API_GLOBAL


def test_los_topes_no_cuentan_los_clics_de_la_web(monkeypatch):
    web = [{"moto_id": 5, "sede_id": 1, "sesion_id": f"visita{i}", "created_at": AHORA.isoformat()}
           for i in range(300)]
    web.append({"moto_id": 5, "sede_id": 1, "sesion_id": None, "created_at": AHORA.isoformat()})
    _base_de_intenciones(monkeypatch, web)
    assert _registrar(5, "conv-1") == inventario.INTENCION_REGISTRADA


def test_moto_inexistente_no_registra(monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    assert _registrar(999, "conv-1") is None
    assert filas == []


@pytest.mark.parametrize("moto_id", [True, False, None, "12", 12.0, 0, -3, [12]])
def test_moto_id_que_no_es_entero_se_rechaza(monkeypatch, moto_id):
    filas = _base_de_intenciones(monkeypatch)
    with pytest.raises(ErrorValidacion):
        _registrar(moto_id, "conv-1")
    assert filas == []


@pytest.mark.parametrize("origen", [123, ["a"], {"a": 1}, "x" * 201])
def test_origen_invalido_se_rechaza(monkeypatch, origen):
    filas = _base_de_intenciones(monkeypatch)
    with pytest.raises(ErrorValidacion):
        _registrar(5, origen)
    assert filas == []


# ------------------------------------------- intenciones, por la ruta HTTP

def test_ruta_intenciones_201_luego_200_duplicada(cliente, monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    # La ruta no pasa 'ahora': sin fijar el reloj del servicio, la fila
    # (fechada en AHORA) sale de la ventana de dedup cuando la fecha real
    # pasa de AHORA + 24 h y la prueba empieza a fallar sola.
    monkeypatch.setattr(inventario, "datetime", _RelojFijo)
    primera = cliente.post("/api/intenciones", json={"moto_id": 5, "origen": "conv-1"},
                           headers=_bearer(LLAVE))
    segunda = cliente.post("/api/intenciones", json={"moto_id": 5, "origen": "conv-1"},
                           headers=_bearer(LLAVE))
    assert (primera.status_code, primera.get_json()) == (201, {"ok": True})
    assert (segunda.status_code, segunda.get_json()) == (200, {"ok": True, "duplicada": True})
    assert len(filas) == 1


@pytest.mark.parametrize("cuerpo", [{"moto_id": True}, {"moto_id": "5"}, {}, [5], "5"])
def test_ruta_intenciones_400(cliente, monkeypatch, cuerpo):
    filas = _base_de_intenciones(monkeypatch)
    respuesta = cliente.post("/api/intenciones", json=cuerpo, headers=_bearer(LLAVE))
    assert respuesta.status_code == 400
    assert filas == []


def test_ruta_intenciones_404(cliente, monkeypatch):
    _base_de_intenciones(monkeypatch)
    respuesta = cliente.post("/api/intenciones", json={"moto_id": 999}, headers=_bearer(LLAVE))
    assert respuesta.status_code == 404


def test_ruta_intenciones_sin_llave_no_registra(cliente, monkeypatch):
    filas = _base_de_intenciones(monkeypatch)
    assert cliente.post("/api/intenciones", json={"moto_id": 5}).status_code == 401
    assert filas == []


def test_ruta_intenciones_tope_es_429_con_warning(cliente, monkeypatch, registro):
    lleno = [{"moto_id": 5, "sede_id": 1, "sesion_id": f"api:{i:032x}", "created_at": AHORA.isoformat()}
             for i in range(inventario.TOPE_INTENCIONES_API_POR_MOTO)]
    filas = _base_de_intenciones(monkeypatch, lleno)
    monkeypatch.setattr(inventario, "datetime", _RelojFijo)
    respuesta = cliente.post("/api/intenciones", json={"moto_id": 5, "origen": "573001234567"},
                             headers=_bearer(LLAVE))
    assert respuesta.status_code == 429
    assert len(filas) == inventario.TOPE_INTENCIONES_API_POR_MOTO
    avisos = [r.getMessage() for r in _lineas_api(registro) if r.levelno == logging.WARNING]
    assert "API: tope de intenciones superado (moto), moto 5." in avisos
    assert "API | POST /api/intenciones | 429 | ip=127.0.0.1 | consumidor=n8n" in avisos
    assert "573001234567" not in registro.text


class _RelojFijo(datetime):
    @classmethod
    def now(cls, tz=None):
        return AHORA

"""
Tests de las alertas del motero (Fase A: crédito) y sus dispositivos push:
validación y recurrencia (servicio puro), las rutas con el repositorio
reemplazado por monkeypatch, y que los módulos neutrales sigan neutrales.
"""

import ast
import base64
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from flask import Flask

from app.motero import repositorio
from app.motero import sesion as sesion_motero
from app.seguridad.validadores import ErrorValidacion
from app.servicios import alertas_motero

HOY = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(alertas_motero, "_hoy", lambda: HOY)


def _b64(n):
    return base64.urlsafe_b64encode(b"\x04" * n).rstrip(b"=").decode()


def _suscripcion(endpoint="https://fcm.googleapis.com/fcm/send/abc123"):
    return {"endpoint": endpoint, "keys": {"p256dh": _b64(65), "auth": _b64(16)}}


# ---------- validación de la alerta de crédito ----------

def test_alerta_credito_valida():
    assert alertas_motero.validar_alerta_credito({"fecha_cuota": "2026-11-15"}) == {
        "tipo": "credito",
        "modo": "fecha",
        "recurrencia": "mensual",
        "fecha_objetivo": "2026-11-15",
        "umbrales_dias": [3, 1],
    }


def test_alerta_credito_ignora_lo_que_no_es_la_fecha():
    """Tipo, recurrencia, umbrales y usuario los fija el servidor, no el formulario."""
    datos = alertas_motero.validar_alerta_credito({
        "fecha_cuota": "2026-11-15", "tipo": "soat", "recurrencia": "ninguna",
        "umbrales_dias": "{0}", "usuario_id": "otro-motero",
    })
    assert datos["tipo"] == "credito" and datos["recurrencia"] == "mensual"
    assert datos["umbrales_dias"] == [3, 1]
    assert "usuario_id" not in datos


@pytest.mark.parametrize("fecha", [
    "2026-10-02",   # hoy - 31: el límite hacia atrás
    "2026-11-02",   # hoy
    "2027-11-03",   # hoy + 366: el límite hacia adelante
    " 2026-12-01 ",
])
def test_alerta_credito_fechas_en_rango(fecha):
    assert alertas_motero.validar_alerta_credito({"fecha_cuota": fecha})["fecha_objetivo"] == fecha.strip()


@pytest.mark.parametrize("fecha", [
    None, "", "15/11/2026", "2026-02-30", "mañana", "2026-10-01", "2027-11-04", 20261115,
])
def test_alerta_credito_fecha_invalida(fecha):
    with pytest.raises(ErrorValidacion) as e:
        alertas_motero.validar_alerta_credito({"fecha_cuota": fecha})
    assert e.value.campo == "fecha_cuota"


def test_rango_fecha_credito():
    assert alertas_motero.rango_fecha_credito() == (date(2026, 10, 2), date(2027, 11, 3))


def test_mensaje_error_alerta():
    assert alertas_motero.mensaje_error_alerta("42501") == "No tienes permiso para hacer eso."
    assert alertas_motero.mensaje_error_alerta("XX000") == alertas_motero.MENSAJE_ERROR_GENERICO
    assert alertas_motero.mensaje_error_alerta(None) == alertas_motero.MENSAJE_ERROR_GENERICO


# ---------- validación del dispositivo ----------

def test_dispositivo_valido_se_reconstruye():
    sus = _suscripcion()
    sus["extra"] = "colado"
    sus["keys"]["otra"] = "x"
    assert alertas_motero.validar_dispositivo({"suscripcion": sus}) == {"suscripcion": _suscripcion()}


@pytest.mark.parametrize("datos", [
    None,
    [],
    {},
    {"suscripcion": _suscripcion("http://fcm.googleapis.com/x")},
    {"suscripcion": _suscripcion("https://169.254.169.254/latest")},
    {"suscripcion": _suscripcion("https://fcm.googleapis.com.atacante.co/x")},
    {"suscripcion": {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": _b64(10), "auth": _b64(16)}}},
])
def test_dispositivo_invalido(datos):
    with pytest.raises(ErrorValidacion):
        alertas_motero.validar_dispositivo(datos)


# ---------- recurrencia ----------

@pytest.mark.parametrize("ancla, recurrencia, hoy, esperada", [
    (date(2026, 11, 15), "mensual", HOY, date(2026, 11, 15)),        # todavía no llega
    (date(2026, 11, 2), "mensual", HOY, date(2026, 11, 2)),          # es hoy
    (date(2026, 10, 15), "mensual", HOY, date(2026, 11, 15)),        # pasó: el mes siguiente
    (date(2026, 10, 1), "mensual", HOY, date(2026, 12, 1)),
    (date(2026, 1, 31), "mensual", date(2026, 2, 10), date(2026, 2, 28)),   # febrero corto
    (date(2026, 1, 31), "mensual", date(2026, 3, 1), date(2026, 3, 31)),    # vuelve al 31
    (date(2028, 1, 31), "mensual", date(2028, 2, 1), date(2028, 2, 29)),    # bisiesto
    (date(2026, 12, 20), "mensual", date(2027, 1, 5), date(2027, 1, 20)),   # cambio de año
    (date(2024, 2, 29), "anual", date(2025, 1, 1), date(2025, 2, 28)),
    (date(2026, 11, 15), "ninguna", HOY, date(2026, 11, 15)),
    (date(2026, 10, 15), "ninguna", HOY, None),
])
def test_proxima_ocurrencia(ancla, recurrencia, hoy, esperada):
    assert alertas_motero.proxima_ocurrencia(ancla, recurrencia, hoy) == esperada


def test_proxima_ocurrencia_recurrencia_desconocida():
    with pytest.raises(ValueError):
        alertas_motero.proxima_ocurrencia(HOY, "semanal", HOY)


def test_para_mostrar():
    filas = alertas_motero.para_mostrar([
        {"id": 1, "tipo": "credito", "modo": "fecha", "fecha_objetivo": "2026-10-15",
         "recurrencia": "mensual", "umbrales_dias": [3, 1]},
    ])
    assert filas[0]["nombre"] == "Cuota del crédito"
    assert filas[0]["proxima"] == "15 de noviembre de 2026"


# ---------- rutas (repositorio y Supabase Auth reemplazados) ----------

@pytest.fixture
def cliente(monkeypatch):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "app" / "templates"))
    app.config.update(SECRET_KEY="test", CLAVE_CIFRADO=Fernet.generate_key(), TESTING=True)
    from app.motero.routes import motero_bp
    app.register_blueprint(motero_bp)

    # Supabase Auth acepta el token de la sesión como de "u-1".
    auth = SimpleNamespace(get_user=lambda jwt: SimpleNamespace(user=SimpleNamespace(id="u-1")))
    monkeypatch.setattr(sesion_motero, "cliente_auth", lambda: SimpleNamespace(auth=auth))

    c = app.test_client()
    with app.test_request_context("/"):
        sesion = SimpleNamespace(
            user=SimpleNamespace(id="u-1", email="m@correo.com"),
            access_token="access-1", refresh_token="refresh-1",
            expires_at=int(time.time()) + 3600)
        from flask import session
        sesion_motero.guardar_sesion_motero(sesion)
        valores = dict(session)
    with c.session_transaction() as s:
        s.update(valores)
    return c


def test_crear_alerta_usa_usuario_de_la_sesion(cliente, monkeypatch):
    creadas = []
    monkeypatch.setattr(repositorio, "contar_alertas", lambda token: 0)
    monkeypatch.setattr(repositorio, "crear_alerta",
                        lambda token, uid, datos: creadas.append((token, uid, datos)) or {"id": 1})
    r = cliente.post("/mi-espacio/alertas/credito",
                     data={"fecha_cuota": "2026-11-15", "usuario_id": "otro-motero"})
    assert r.status_code == 302 and r.location.endswith("/mi-espacio#alertas")
    assert creadas == [("access-1", "u-1", alertas_motero.validar_alerta_credito({"fecha_cuota": "2026-11-15"}))]


def test_crear_alerta_respeta_el_tope(cliente, monkeypatch):
    monkeypatch.setattr(repositorio, "contar_alertas", lambda token: alertas_motero.MAX_ALERTAS_POR_MOTERO)
    monkeypatch.setattr(repositorio, "crear_alerta", lambda *a: pytest.fail("no debía insertar"))
    # La página de error se renderiza con todo el contexto: se reemplaza.
    import app.motero.routes as rutas
    monkeypatch.setattr(rutas, "_pagina_mi_espacio", lambda estado=200, **extra: (extra.get("error_alerta", ""), estado))
    r = cliente.post("/mi-espacio/alertas/credito", data={"fecha_cuota": "2026-11-15"})
    assert r.status_code == 400
    assert r.get_data(as_text=True) == alertas_motero.MENSAJE_TOPE_ALERTAS


def test_borrar_alerta_ajena_da_404(cliente, monkeypatch):
    monkeypatch.setattr(repositorio, "borrar_alerta", lambda token, alerta_id: None)
    import app.motero.routes as rutas
    monkeypatch.setattr(rutas, "_pagina_mi_espacio", lambda estado=200, **extra: ("", estado))
    assert cliente.post("/mi-espacio/alertas/99/borrar").status_code == 404


def test_borrar_alerta_propia(cliente, monkeypatch):
    monkeypatch.setattr(repositorio, "borrar_alerta", lambda token, alerta_id: {"id": alerta_id})
    r = cliente.post("/mi-espacio/alertas/7/borrar")
    assert r.status_code == 302


def test_guardar_dispositivo(cliente, monkeypatch):
    guardados = []
    monkeypatch.setattr(repositorio, "guardar_dispositivo",
                        lambda token, uid, sus: guardados.append((uid, sus)) or {"id": 1})
    r = cliente.post("/mi-espacio/dispositivos",
                     json={"suscripcion": _suscripcion(), "usuario_id": "otro-motero"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert guardados == [("u-1", _suscripcion())]


def test_guardar_dispositivo_rechaza_endpoint_arbitrario(cliente, monkeypatch):
    monkeypatch.setattr(repositorio, "guardar_dispositivo", lambda *a: pytest.fail("no debía guardar"))
    r = cliente.post("/mi-espacio/dispositivos", json={"suscripcion": _suscripcion("https://10.0.0.1/x")})
    assert r.status_code == 400 and "error" in r.get_json()


def test_rutas_exigen_sesion(monkeypatch):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", CLAVE_CIFRADO=Fernet.generate_key())
    from app.motero.routes import motero_bp
    app.register_blueprint(motero_bp)
    c = app.test_client()
    for url in ("/mi-espacio/dispositivos", "/mi-espacio/alertas/credito", "/mi-espacio/alertas/1/borrar"):
        r = c.post(url)
        assert r.status_code == 302 and "/ingresar" in r.location


# ---------- módulos neutrales ----------

@pytest.mark.parametrize("modulo", ["tiempo.py", "suscripcion_push.py"])
def test_modulo_neutral(modulo):
    """Los usan el panel y el motero: no pueden importar nada de app (salvo validadores), supabase ni config."""
    raiz = Path(__file__).resolve().parents[1]
    arbol = ast.parse((raiz / "app" / "seguridad" / modulo).read_text(encoding="utf-8"))
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            modulos.add(nodo.module or "")
    prohibidos = [m for m in modulos
                  if m.startswith(("app", "supabase", "config")) and m != "app.seguridad.validadores"]
    assert not prohibidos, prohibidos

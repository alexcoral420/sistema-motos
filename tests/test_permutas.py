"""
Pruebas del registro de permutas (inventario.registrar_permuta), su
contrato y el reporte "Permutas por asesor" (reportes.permutas_por_usuario).

No tocan la base: el repositorio, el alcance de sede y la lista de sedes
se reemplazan con monkeypatch.
Correr desde la raíz del proyecto:  python -m pytest tests/
"""

import re
from pathlib import Path

import pytest
from flask import Flask
from postgrest.exceptions import APIError
from werkzeug.datastructures import ImmutableMultiDict

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import contratos, inventario, personas, reportes, sedes

SEDE_NORTE = 1
SEDE_SUR = 2
RAIZ = Path(__file__).resolve().parent.parent

MOTO_SALIENTE = {"id": 50, "placa": "XYZ987", "sede_id": SEDE_NORTE,
                 "estado": "disponible", "marca": "HONDA", "modelo": "CB190", "anio": 2021,
                 "sedes": {"nombre": "av 1 de mayo"}}

RUNT_SALIENTE = {"placa": "XYZ987", "numero_chasis": "CHASIS-S", "numero_motor": "MOTOR-S",
                 "marca": "HONDA", "linea": "CB190"}

ASESORES = {
    7: {"id": 7, "rol": "asesor", "activo": True, "sede_id": SEDE_NORTE, "nombre_completo": "Ana Asesora"},
    8: {"id": 8, "rol": "asesor", "activo": True, "sede_id": SEDE_SUR, "nombre_completo": "Beto Sur"},
    9: {"id": 9, "rol": "asesor", "activo": False, "sede_id": SEDE_NORTE, "nombre_completo": "Ex Asesor"},
    3: {"id": 3, "rol": "encargado_sede", "activo": True, "sede_id": SEDE_NORTE, "nombre_completo": "Encargado"},
}

RUNT_ENTRANTE = """
PLACA DEL VEHÍCULO:
ABC123
MARCA
YAMAHA
LÍNEA
FZ 2.0
MODELO
2020
COLOR
NEGRO
CILINDRAJE
149.00 CC
NÚMERO DE MOTOR
G3S8E0123456
NÚMERO DE CHASIS
9FKRG0123456
"""


def formulario(**cambios):
    # Neto: 10.000.000 - 8.000.000 + 500.000 = 2.500.000, paga el cliente.
    campos = {
        "placa_saliente": " xyz987 ",
        "asesor_id": "7",
        "texto_runt": RUNT_ENTRANTE,
        "propietario_registrado": "Carlos Propietario",
        "cliente_nombre": "Carla Cliente",
        "cliente_cedula": "1.234.567",
        "cliente_telefono": "300 123 4567",
        "valor_saliente": "10000000",
        "valor_entrante": "8000000",
        "valor_traspaso": "500000",
        "pago_metodo": ["efectivo"],
        "pago_entidad": [""],
        "pago_monto": ["2500000"],
        # Una sede manipulada en el form no debe usarse.
        "sede_id": str(SEDE_SUR),
    }
    campos.update(cambios)
    return ImmutableMultiDict(campos)


@pytest.fixture
def entorno(monkeypatch):
    """Repositorio falso: una moto disponible con RUNT en la sede norte, en alcance."""
    llamadas = []

    monkeypatch.setattr(sedes, "ids_validos", lambda: {str(SEDE_NORTE), str(SEDE_SUR)})
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [dict(MOTO_SALIENTE)] if placa == "XYZ987" else [])
    monkeypatch.setattr(inventario, "moto_en_alcance", lambda moto_id: dict(MOTO_SALIENTE))
    monkeypatch.setattr(repositorios, "obtener_usuario_por_id", lambda uid: ASESORES.get(uid))
    monkeypatch.setattr(repositorios, "obtener_datos_contrato", lambda moto_id: dict(RUNT_SALIENTE))
    monkeypatch.setattr(personas, "obtener_o_crear", lambda datos: 40)

    def registrar(*args):
        llamadas.append(args)
        return {"permuta_id": 1, "moto_entrante_id": 99}

    monkeypatch.setattr(repositorios, "registrar_permuta_moto", registrar)
    return llamadas


def registrar(form):
    return inventario.registrar_permuta(form, 3, "Encargado")


# ------------------------------------------------------------
#  Formulario y errores del RPC
# ------------------------------------------------------------

def test_formulario_registra_en_permuta_y_solo_runt_usa_formaction():
    """Tras "Cargar del RUNT" la URL es /desde-runt: sin action, registrar caería ahí."""
    plantilla = (RAIZ / "app/templates/permuta.html").read_text(encoding="utf-8")

    formulario_html = re.search(r"<form\b[^>]*>", plantilla).group(0)
    assert "action=\"{{ url_for('admin.permuta') }}\"" in formulario_html

    botones = re.findall(r"<button\b.*?</button>", plantilla, re.DOTALL)
    runt = next(b for b in botones if "Cargar del RUNT" in b)
    boton_registrar = next(b for b in botones if 'id="btn-permuta"' in b)
    assert "url_for('admin.permuta_desde_runt')" in runt and "formnovalidate" in runt
    assert "formaction" not in boton_registrar


class _ClienteQueFalla:
    """Cliente Supabase falso cuyo RPC termina en el error indicado."""

    def __init__(self, error):
        self.error = error

    def rpc(self, nombre, parametros):
        return self

    def execute(self):
        raise self.error


def _registrar_con_error(monkeypatch, error):
    monkeypatch.setattr(repositorios, "get_supabase_admin", lambda: _ClienteQueFalla(error))
    return repositorios.registrar_permuta_moto(
        50, {}, 3, "Encargado", 7, "Ana Asesora", {}, 40, 10, 8, 0, [])


def test_rpc_p0001_conserva_el_mensaje_de_postgres(monkeypatch):
    error = APIError({"message": "La moto que sale no existe.", "code": "P0001",
                      "details": None, "hint": None})
    with pytest.raises(ErrorValidacion) as e:
        _registrar_con_error(monkeypatch, error)
    assert e.value.mensaje == "La moto que sale no existe."


def test_rpc_otro_error_muestra_codigo_mensaje_y_detalle(monkeypatch):
    error = APIError({"message": "null value in column", "code": "23502",
                      "details": "Failing row contains", "hint": "revisar"})
    with pytest.raises(ErrorValidacion) as e:
        _registrar_con_error(monkeypatch, error)
    for parte in ("23502", "null value in column", "Failing row contains", "revisar"):
        assert parte in e.value.mensaje


# ------------------------------------------------------------
#  Registro: atribución, sede y saliente
# ------------------------------------------------------------

def test_registra_con_asesor_cliente_valores_y_quien_registra_de_sesion(entorno):
    assert registrar(formulario()) == {"permuta_id": 1, "moto_entrante_id": 99}
    (saliente_id, entrante, usuario_id, usuario_nombre, asesor_id, asesor_nombre,
     datos_contrato, persona_id, valor_saliente, valor_entrante, valor_traspaso,
     pagos) = entorno[0]
    assert saliente_id == 50
    assert (usuario_id, usuario_nombre) == (3, "Encargado")
    assert (asesor_id, asesor_nombre) == (7, "Ana Asesora")
    assert persona_id == 40
    assert (valor_saliente, valor_entrante, valor_traspaso) == (10000000, 8000000, 500000)
    assert pagos == [{"metodo": "efectivo", "entidad": None, "monto": 2500000}]
    assert entrante["placa"] == "ABC123" and entrante["estado"] == "por_publicar"
    assert datos_contrato["numero_motor"] == "G3S8E0123456"


def test_la_entrante_queda_en_la_sede_de_la_saliente_no_la_del_form(entorno):
    registrar(formulario(sede_id=str(SEDE_SUR)))
    assert entorno[0][1]["sede_id"] == SEDE_NORTE


def test_sin_asesor_no_registra(entorno):
    with pytest.raises(ErrorValidacion):
        registrar(formulario(asesor_id=""))
    assert entorno == []


@pytest.mark.parametrize("asesor_id", ["8", "9", "3", "999"])
def test_asesor_de_otra_sede_inactivo_o_no_asesor_se_rechaza(entorno, asesor_id):
    with pytest.raises(ErrorValidacion, match="asesor"):
        registrar(formulario(asesor_id=asesor_id))
    assert entorno == []


def test_placa_saliente_inexistente_dice_que_no_existe(entorno):
    with pytest.raises(ErrorValidacion, match="No existe ninguna moto con placa NOEXISTE"):
        registrar(formulario(placa_saliente="noexiste"))
    assert entorno == []


@pytest.mark.parametrize("estado", ["por_publicar", "reservado", "vendido"])
def test_saliente_no_disponible_dice_su_estado(entorno, monkeypatch, estado):
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [{**MOTO_SALIENTE, "estado": estado}])
    with pytest.raises(ErrorValidacion, match=f"no está disponible: su estado es '{estado}'"):
        registrar(formulario())
    assert entorno == []


def test_saliente_de_otra_sede_dice_de_que_sede_es(entorno, monkeypatch):
    monkeypatch.setattr(inventario, "moto_en_alcance", lambda moto_id: None)
    with pytest.raises(ErrorValidacion, match="es de la sede av 1 de mayo, no de la suya"):
        registrar(formulario())
    assert entorno == []


def test_placa_repetida_usa_la_disponible_y_no_la_vendida(entorno, monkeypatch):
    vendida = {**MOTO_SALIENTE, "id": 10, "estado": "vendido"}
    # La vendida es la más reciente, pero la que sale es la disponible.
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [vendida, dict(MOTO_SALIENTE)])
    registrar(formulario())
    assert entorno[0][0] == 50


@pytest.mark.parametrize("datos, falta", [
    (None, "número de chasis"),
    ({**RUNT_SALIENTE, "numero_chasis": " "}, "número de chasis"),
    ({**RUNT_SALIENTE, "numero_motor": None}, "número de motor"),
])
def test_saliente_sin_runt_indica_cargarlo_en_su_detalle(entorno, monkeypatch, datos, falta):
    monkeypatch.setattr(repositorios, "obtener_datos_contrato", lambda moto_id: datos)
    with pytest.raises(ErrorValidacion) as e:
        registrar(formulario())
    assert falta in e.value.mensaje
    assert "XYZ987" in e.value.mensaje and "detalle de esa moto" in e.value.mensaje
    assert entorno == []


# ------------------------------------------------------------
#  Moto que entra: sale del RUNT
# ------------------------------------------------------------

def test_entrante_sale_solo_del_runt_e_ignora_campos_del_form(entorno):
    registrar(formulario(marca="otra", precio="1", kilometraje="5"))
    entrante = entorno[0][1]
    assert entrante["marca"] == "YAMAHA"
    assert entrante["modelo"] == "FZ 2.0"
    assert entrante["anio"] == 2020
    assert entrante["cilindraje"] == 149
    assert entrante["precio"] is None and entrante["kilometraje"] is None


def test_datos_contrato_incluye_runt_y_propietario(entorno):
    registrar(formulario())
    datos_contrato = entorno[0][6]
    manuales = {"propietario_registrado", "manifiesto_aduana", "fecha_manifiesto"}
    assert set(datos_contrato) == set(contratos.COLUMNAS) | manuales
    assert datos_contrato["propietario_registrado"] == "Carlos Propietario"
    assert datos_contrato["numero_vin"] is None


@pytest.mark.parametrize("propietario", ["", "ab"])
def test_propietario_registrado_es_obligatorio(entorno, propietario):
    with pytest.raises(ErrorValidacion, match="propietario registrado"):
        registrar(formulario(propietario_registrado=propietario))
    assert entorno == []


def test_runt_de_entrante_es_obligatorio(entorno):
    with pytest.raises(ErrorValidacion, match="obligatoria"):
        registrar(formulario(texto_runt="  "))
    assert entorno == []


def test_runt_ilegible_no_registra(entorno):
    with pytest.raises(ErrorValidacion, match="RUNT"):
        registrar(formulario(texto_runt="esto no es una consulta"))
    assert entorno == []


@pytest.mark.parametrize("campo, nombre", [
    ("placa", "la placa"), ("marca", "la marca"), ("linea", "la línea"),
    ("numero_chasis", "el número de chasis"), ("numero_motor", "el número de motor"),
])
def test_runt_sin_dato_que_identifica_la_moto_lo_nombra(campo, nombre):
    datos = {"placa": "ABC123", "marca": "YAMAHA", "linea": "FZ",
             "numero_chasis": "C", "numero_motor": "M"}
    datos.pop(campo)
    with pytest.raises(ErrorValidacion, match=nombre):
        inventario.entrante_desde_runt(datos, SEDE_NORTE)


def test_runt_incompleto_o_fuera_de_rango_no_bloquea_lo_demas():
    moto = inventario.entrante_desde_runt(
        {"placa": "abc-123", "marca": "Yamaha", "linea": "Fz", "numero_chasis": "C",
         "numero_motor": "M", "cilindraje": "0"}, SEDE_NORTE)
    assert moto["placa"] == "ABC123"
    assert moto["anio"] is None and moto["color"] is None and moto["cilindraje"] is None


# ------------------------------------------------------------
#  Cliente
# ------------------------------------------------------------

def test_cliente_se_resuelve_por_cedula_normalizada(entorno, monkeypatch):
    recibido = {}
    monkeypatch.setattr(personas, "obtener_o_crear", lambda d: recibido.update(d) or 40)
    registrar(formulario())
    assert recibido["cedula"] == "1234567"
    assert recibido["telefono"] == "3001234567"


@pytest.mark.parametrize("cambio, mensaje", [
    ({"cliente_telefono": ""}, "teléfono del cliente"),
    ({"cliente_cedula": ""}, "cédula"),
    ({"cliente_nombre": ""}, "nombre del cliente"),
    ({"cliente_correo": "sinarroba"}, "correo del cliente"),
])
def test_cliente_invalido_tiene_mensaje_propio(entorno, cambio, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        registrar(formulario(**cambio))
    assert entorno == []


# ------------------------------------------------------------
#  Dinero
# ------------------------------------------------------------

@pytest.mark.parametrize("saliente, entrante, traspaso, neto, paga", [
    (10, 8, 1, 3, "cliente"),
    (8, 10, 1, -1, "empresa"),
    (8, 9, 1, 0, "nadie"),
])
def test_neto_y_quien_paga(saliente, entrante, traspaso, neto, paga):
    assert inventario.calcular_neto(saliente, entrante, traspaso) == neto
    assert inventario.quien_paga(neto) == paga


def pago(metodo="efectivo", monto="100", entidad=""):
    return {"metodo": metodo, "entidad": entidad, "monto": monto}


def test_neto_negativo_valida_contra_el_valor_absoluto():
    pagos = inventario.validar_pagos_permuta([pago(monto="300")], 700, 1200, 200)
    assert pagos == [{"metodo": "efectivo", "entidad": None, "monto": 300}]


def test_pagos_que_no_cuadran_dicen_cuanto_y_por_que():
    with pytest.raises(ErrorValidacion) as e:
        inventario.validar_pagos_permuta([pago(monto="2000000")], 10000000, 8000000, 500000)
    assert "Los pagos suman $2.000.000, pero deben sumar $2.500.000" in e.value.mensaje
    assert "paga el cliente" in e.value.mensaje
    assert "Diferencia: $500.000" in e.value.mensaje


def test_varios_pagos_suman_el_neto():
    pagos = inventario.validar_pagos_permuta(
        [pago("efectivo", "60"), pago("financiado", "40", "addi")], 150, 50, 0)
    assert [p["monto"] for p in pagos] == [60, 40]
    assert pagos[1]["entidad"] == "addi"


def test_neto_cero_no_lleva_pagos_y_la_fila_vacia_se_ignora():
    assert inventario.validar_pagos_permuta([pago(monto="")], 100, 100, 0) == []
    with pytest.raises(ErrorValidacion, match=r"neto de la permuta es \$0"):
        inventario.validar_pagos_permuta([pago(monto="5")], 100, 100, 0)


def test_con_neto_positivo_exige_pagos():
    with pytest.raises(ErrorValidacion, match="el cliente debe pagar"):
        inventario.validar_pagos_permuta([pago(monto="")], 100, 50, 0)


def test_empresa_no_puede_pagar_financiado():
    with pytest.raises(ErrorValidacion, match="paga la empresa"):
        inventario.validar_pagos_permuta([pago("financiado", "50", "addi")], 50, 100, 0)


@pytest.mark.parametrize("metodo", ["permuta", "bitcoin"])
def test_metodo_no_admitido(metodo):
    with pytest.raises(ErrorValidacion, match="Método de pago inválido"):
        inventario.validar_pagos_permuta([pago(metodo, "50")], 100, 50, 0)


def test_financiado_exige_entidad():
    with pytest.raises(ErrorValidacion, match="entidad financiera"):
        inventario.validar_pagos_permuta([pago("financiado", "50", "")], 100, 50, 0)


@pytest.mark.parametrize("cambio, mensaje", [
    ({"valor_saliente": ""}, "moto que sale"),
    ({"valor_entrante": "0"}, "moto que entra"),
    ({"valor_traspaso": "-1"}, "traspaso"),
])
def test_valores_invalidos_no_registran(entorno, cambio, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        registrar(formulario(**cambio))
    assert entorno == []


def test_no_crea_la_persona_si_los_pagos_no_cuadran(entorno, monkeypatch):
    creadas = []
    monkeypatch.setattr(personas, "obtener_o_crear", lambda d: creadas.append(d) or 40)
    with pytest.raises(ErrorValidacion):
        registrar(formulario(pago_monto=["1"]))
    assert creadas == [] and entorno == []


# ------------------------------------------------------------
#  Rutas: formulario sticky y PRG
# ------------------------------------------------------------

@pytest.fixture
def panel(monkeypatch):
    """Cliente HTTP del panel con sesión de encargado y repositorio falso."""
    from app.admin import routes as admin_routes

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True)
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.jinja_env.filters["pesos"] = contratos._formatear_pesos
    app.register_blueprint(admin_routes.admin_bp)

    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    monkeypatch.setattr(inventario, "asesores_para_permuta",
                        lambda: [{"id": 7, "nombre_completo": "Ana Asesora", "sede_nombre": ""}])

    cliente = app.test_client()
    with cliente.session_transaction() as s:
        s.update(logueado=True, rol="encargado_sede", sede_id=SEDE_NORTE,
                 usuario_id=3, usuario_nombre="Encargado")
    return cliente


def datos_post(**cambios):
    return formulario(**cambios).to_dict(flat=False)


def test_cargar_runt_muestra_vista_previa_y_conserva_todo(panel):
    respuesta = panel.post("/admin/permuta/desde-runt", data=datos_post(
        pago_metodo=["efectivo", "financiado"], pago_entidad=["", "addi"],
        pago_monto=["1000000", "1500000"]))
    html = respuesta.get_data(as_text=True)

    assert respuesta.status_code == 200
    assert "G3S8E0123456" in html                     # vista previa del RUNT
    assert 'value="Carla Cliente"' in html
    assert 'value="10000000"' in html
    assert '"monto": "1500000"' in html and '"entidad": "addi"' in html


def test_error_de_dinero_repinta_con_lo_cargado_y_el_mensaje_exacto(panel, entorno):
    respuesta = panel.post("/admin/permuta", data=datos_post(pago_monto=["2000000"]))
    html = respuesta.get_data(as_text=True)

    assert respuesta.status_code == 200
    assert "Los pagos suman $2.000.000, pero deben sumar $2.500.000" in html
    assert 'value="Carla Cliente"' in html and '"monto": "2000000"' in html
    assert entorno == []


def test_registro_exitoso_redirige_a_la_confirmacion(panel, entorno):
    respuesta = panel.post("/admin/permuta", data=datos_post())
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/admin/permuta/1/registrada")


def test_formulario_vacio_se_pinta_sin_campos_de_publicacion(panel):
    respuesta = panel.get("/admin/permuta")
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert 'name="propietario_registrado"' in html
    assert 'name="precio"' not in html and 'name="marca"' not in html


def test_confirmacion_muestra_contrato_y_enlace_a_la_entrante(panel, monkeypatch):
    permuta = {"id": 1, "moto_entrante_id": 99, "descripcion_saliente": "HONDA CB190 2021",
               "descripcion_entrante": "YAMAHA FZ 2020", "asesor_nombre": "Ana Asesora"}
    monkeypatch.setattr(inventario, "permuta_en_alcance", lambda permuta_id: permuta)
    monkeypatch.setattr(inventario, "resumen_permuta", lambda p: {
        "cliente": {"nombre": "Carla Cliente"}, "neto": 2500000, "quien_paga": "cliente",
        "pagos": [{"linea": "Efectivo", "monto": 2500000}]})

    html = panel.get("/admin/permuta/1/registrada?contrato_error=Sin+plantilla").get_data(as_text=True)
    assert "/admin/permuta/1/contrato" in html and "/admin/moto/99" in html
    assert "Sin plantilla" in html and "$2.500.000" in html and "paga el cliente" in html


def test_confirmacion_de_otra_sede_es_403(panel, monkeypatch):
    monkeypatch.setattr(inventario, "permuta_en_alcance", lambda permuta_id: None)
    assert panel.get("/admin/permuta/1/registrada").status_code == 403


# ------------------------------------------------------------
#  Alcance y contrato
# ------------------------------------------------------------

@pytest.mark.parametrize("alcance, sede_permuta, visible", [
    (SEDE_NORTE, SEDE_NORTE, True),
    (SEDE_NORTE, SEDE_SUR, False),
    (None, SEDE_NORTE, False),
    (inventario.TODAS_LAS_SEDES, SEDE_SUR, True),
])
def test_permuta_en_alcance(monkeypatch, alcance, sede_permuta, visible):
    monkeypatch.setattr(inventario, "_sede_del_alcance", lambda: alcance)
    monkeypatch.setattr(repositorios, "obtener_permuta_por_id",
                        lambda pid: {"id": pid, "sede_id": sede_permuta})
    assert (inventario.permuta_en_alcance(1) is not None) is visible


PERMUTA = {"id": 1, "persona_id": 40, "moto_saliente_id": 50, "moto_entrante_id": 99,
           "valor_saliente": 8000000, "valor_entrante": 10000000, "valor_traspaso": 500000,
           "created_at": "2026-11-09T15:00:00+00:00", "sede_id": SEDE_NORTE}
RUNT_ENTRANTE_GUARDADO = {"placa": "ABC123", "numero_chasis": "CHASIS-E", "numero_motor": "MOTOR-E",
                          "propietario_registrado": "Carlos Propietario"}


@pytest.fixture
def contrato(monkeypatch, tmp_path):
    """Entorno del contrato: devuelve el contexto con el que se rellena la plantilla."""
    plantilla = tmp_path / "contrato_permuta.docx"
    plantilla.write_bytes(b"")
    monkeypatch.setattr(contratos, "PLANTILLA_CONTRATO_PERMUTA", plantilla)
    monkeypatch.setattr(inventario, "permuta_en_alcance", lambda pid: dict(PERMUTA))
    monkeypatch.setattr(repositorios, "obtener_datos_contrato",
                        lambda mid: RUNT_SALIENTE if mid == 50 else RUNT_ENTRANTE_GUARDADO)
    monkeypatch.setattr(repositorios, "obtener_persona_por_id", lambda pid: {
        "nombre": "Carla Cliente", "cedula": "1234567", "telefono": "3001234567"})
    monkeypatch.setattr(repositorios, "obtener_pagos_de_permuta", lambda pid: [
        {"metodo": "transferencia", "entidad": None, "monto": 1500000}])

    capturado = {}

    def renderizar(ruta, contexto, respaldo):
        capturado.update(contexto)
        return "docx", contexto["placa"]

    monkeypatch.setattr(contratos, "_renderizar", renderizar)
    app = Flask(__name__)
    app.config["NIT"] = "900"
    with app.app_context():
        yield capturado


def test_contrato_usa_valores_congelados_y_las_dos_motos(contrato):
    assert contratos.generar_contrato_permuta(1) == ("docx", "contrato_permuta_XYZ987.docx")
    assert contrato["saliente_chasis"] == "CHASIS-S"
    assert contrato["entrante_chasis"] == "CHASIS-E"
    assert contrato["cliente"] == "Carla Cliente"
    assert contrato["propietario"] == "Carlos Propietario"
    assert contrato["excedente"] == "2.000.000" and contrato["excedente_a_favor"] == "cliente"
    assert contrato["neto"] == "1.500.000" and contrato["quien_paga"] == "empresa"
    assert contrato["traspaso"] == "500.000"
    assert contrato["fecha"] == "09/11/2026"
    assert contrato["pagos"] == [{"linea": "Transferencia", "monto": "1.500.000"}]


def test_sin_plantilla_avisa_y_no_rompe(contrato, monkeypatch, tmp_path):
    monkeypatch.setattr(contratos, "PLANTILLA_CONTRATO_PERMUTA", tmp_path / "no_existe.docx")
    with pytest.raises(ErrorValidacion, match="plantilla .* aún no está cargada"):
        contratos.generar_contrato_permuta(1)


def test_permuta_historica_no_tiene_contrato(contrato, monkeypatch):
    monkeypatch.setattr(inventario, "permuta_en_alcance",
                        lambda pid: {**PERMUTA, "persona_id": None, "valor_saliente": None})
    with pytest.raises(ErrorValidacion, match="anterior al registro con contrato"):
        contratos.generar_contrato_permuta(1)


def test_permuta_de_otra_sede_no_genera_contrato(contrato, monkeypatch):
    monkeypatch.setattr(inventario, "permuta_en_alcance", lambda pid: None)
    with pytest.raises(ErrorValidacion, match="no pertenece a su sede"):
        contratos.generar_contrato_permuta(1)


def test_contrato_nombra_lo_que_falta(contrato, monkeypatch):
    monkeypatch.setattr(repositorios, "obtener_datos_contrato",
                        lambda mid: {**RUNT_SALIENTE, "numero_motor": ""} if mid == 50
                        else RUNT_ENTRANTE_GUARDADO)
    with pytest.raises(ErrorValidacion, match="número de motor de la moto que sale"):
        contratos.generar_contrato_permuta(1)


def test_marcadores_de_la_plantilla_existen_en_el_contexto(contrato):
    """Un marcador mal escrito saldría en blanco sin error."""
    ruta = RAIZ / "app/plantillas/contrato_permuta.docx"
    if not ruta.exists():
        pytest.skip("La plantilla del contrato de permuta aún no está cargada.")
    from docxtpl import DocxTemplate

    contratos.generar_contrato_permuta(1)
    desconocidos = DocxTemplate(str(ruta)).get_undeclared_template_variables(context=contrato)
    assert desconocidos == set()


# ------------------------------------------------------------
#  Reporte
# ------------------------------------------------------------

def test_reporte_cuenta_por_asesor_no_por_quien_registra(monkeypatch):
    filas = [
        {"asesor_nombre": "Ana Asesora", "created_at": "2026-11-01T10:00:00+00:00"},
        {"asesor_nombre": "Beto Sur", "created_at": "2026-11-02T10:00:00+00:00"},
        {"asesor_nombre": "Ana Asesora", "created_at": "2026-11-03T10:00:00+00:00"},
    ]
    monkeypatch.setattr(repositorios, "reporte_permutas_por_usuario",
                        lambda desde=None, hasta=None: filas)

    assert reportes.permutas_por_usuario() == [
        {"asesor_nombre": "Ana Asesora", "total_permutas": 2},
        {"asesor_nombre": "Beto Sur", "total_permutas": 1},
    ]

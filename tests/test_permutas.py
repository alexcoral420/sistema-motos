"""
Pruebas del registro de permutas (inventario.registrar_permuta) y del
reporte "Permutas por asesor" (reportes.permutas_por_usuario).

No tocan la base: el repositorio, el alcance de sede y la lista de sedes
se reemplazan con monkeypatch.
Correr desde la raíz del proyecto:  python -m pytest tests/
"""

import re
from pathlib import Path

import pytest
from postgrest.exceptions import APIError
from werkzeug.datastructures import ImmutableMultiDict

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import contratos, inventario, reportes, sedes

SEDE_NORTE = 1
SEDE_SUR = 2

MOTO_SALIENTE = {"id": 50, "placa": "XYZ987", "sede_id": SEDE_NORTE,
                 "estado": "disponible", "marca": "HONDA", "modelo": "CB190", "anio": 2021,
                 "sedes": {"nombre": "av 1 de mayo"}}

ASESORES = {
    7: {"id": 7, "rol": "asesor", "activo": True, "sede_id": SEDE_NORTE, "nombre_completo": "Ana Asesora"},
    8: {"id": 8, "rol": "asesor", "activo": True, "sede_id": SEDE_SUR, "nombre_completo": "Beto Sur"},
    9: {"id": 9, "rol": "asesor", "activo": False, "sede_id": SEDE_NORTE, "nombre_completo": "Ex Asesor"},
    3: {"id": 3, "rol": "encargado_sede", "activo": True, "sede_id": SEDE_NORTE, "nombre_completo": "Encargado"},
}


def formulario(**cambios):
    campos = {
        "placa_saliente": " xyz987 ",
        "asesor_id": "7",
        "marca": "yamaha", "modelo": "fz", "anio": "2020",
        "cilindraje": "150", "color": "Negro", "placa": "abc123",
        "precio": "8500000", "kilometraje": "12000",
        # Una sede manipulada en el form no debe usarse.
        "sede_id": str(SEDE_SUR),
    }
    campos.update(cambios)
    return ImmutableMultiDict(campos)


@pytest.fixture
def entorno(monkeypatch):
    """Repositorio falso: una moto disponible en la sede norte, en alcance."""
    llamadas = []

    monkeypatch.setattr(sedes, "ids_validos", lambda: {str(SEDE_NORTE), str(SEDE_SUR)})
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [dict(MOTO_SALIENTE)] if placa == "XYZ987" else [])
    monkeypatch.setattr(inventario, "moto_en_alcance", lambda moto_id: dict(MOTO_SALIENTE))
    monkeypatch.setattr(repositorios, "obtener_usuario_por_id", lambda uid: ASESORES.get(uid))

    def registrar(*args):
        llamadas.append(args)
        return {"permuta_id": 1, "moto_entrante_id": 99}

    monkeypatch.setattr(repositorios, "registrar_permuta_moto", registrar)
    return llamadas


def test_formulario_registra_en_permuta_y_solo_runt_usa_formaction():
    """Tras "Cargar del RUNT" la URL es /desde-runt: sin action, registrar caería ahí."""
    plantilla = (Path(__file__).parent.parent / "app/templates/permuta.html").read_text(encoding="utf-8")

    formulario_html = re.search(r"<form\b[^>]*>", plantilla).group(0)
    assert "action=\"{{ url_for('admin.permuta') }}\"" in formulario_html

    botones = re.findall(r"<button\b.*?</button>", plantilla, re.DOTALL)
    runt = next(b for b in botones if "Cargar del RUNT" in b)
    registrar = next(b for b in botones if 'id="btn-permuta"' in b)
    assert "url_for('admin.permuta_desde_runt')" in runt and "formnovalidate" in runt
    assert "formaction" not in registrar


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
    return repositorios.registrar_permuta_moto(50, {}, 3, "Encargado", 7, "Ana Asesora")


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


def test_registra_con_el_asesor_elegido_y_quien_registra_de_sesion(entorno):
    resultado = inventario.registrar_permuta(formulario(), 3, "Encargado")

    assert resultado == {"permuta_id": 1, "moto_entrante_id": 99}
    (saliente_id, entrante, usuario_id, usuario_nombre,
     asesor_id, asesor_nombre, datos_contrato) = entorno[0]
    assert saliente_id == 50
    assert (usuario_id, usuario_nombre) == (3, "Encargado")
    assert (asesor_id, asesor_nombre) == (7, "Ana Asesora")
    assert entrante["marca"] == "YAMAHA" and entrante["placa"] == "ABC123"
    assert entrante["estado"] == "por_publicar"
    assert datos_contrato is None   # sin RUNT pegado, sin datos de contrato


def test_la_entrante_queda_en_la_sede_de_la_saliente_no_la_del_form(entorno):
    inventario.registrar_permuta(formulario(sede_id=str(SEDE_SUR)), 3, "Encargado")
    entrante = entorno[0][1]
    assert entrante["sede_id"] == SEDE_NORTE


def test_sin_asesor_no_registra(entorno):
    with pytest.raises(ErrorValidacion):
        inventario.registrar_permuta(formulario(asesor_id=""), 3, "Encargado")
    assert entorno == []


@pytest.mark.parametrize("asesor_id", ["8", "9", "3", "999"])
def test_asesor_de_otra_sede_inactivo_o_no_asesor_se_rechaza(entorno, asesor_id):
    with pytest.raises(ErrorValidacion, match="asesor"):
        inventario.registrar_permuta(formulario(asesor_id=asesor_id), 3, "Encargado")
    assert entorno == []


def test_placa_saliente_inexistente_dice_que_no_existe(entorno):
    with pytest.raises(ErrorValidacion, match="No existe ninguna moto con placa NOEXISTE"):
        inventario.registrar_permuta(formulario(placa_saliente="noexiste"), 3, "Encargado")
    assert entorno == []


@pytest.mark.parametrize("estado", ["por_publicar", "reservado", "vendido"])
def test_saliente_no_disponible_dice_su_estado(entorno, monkeypatch, estado):
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [{**MOTO_SALIENTE, "estado": estado}])
    with pytest.raises(ErrorValidacion, match=f"no está disponible: su estado es '{estado}'"):
        inventario.registrar_permuta(formulario(), 3, "Encargado")
    assert entorno == []


def test_saliente_de_otra_sede_dice_de_que_sede_es(entorno, monkeypatch):
    monkeypatch.setattr(inventario, "moto_en_alcance", lambda moto_id: None)
    with pytest.raises(ErrorValidacion, match="es de la sede av 1 de mayo, no de la suya"):
        inventario.registrar_permuta(formulario(), 3, "Encargado")
    assert entorno == []


def test_placa_repetida_usa_la_disponible_y_no_la_vendida(entorno, monkeypatch):
    vendida = {**MOTO_SALIENTE, "id": 10, "estado": "vendido"}
    # La vendida es la más reciente, pero la que sale es la disponible.
    monkeypatch.setattr(repositorios, "obtener_motos_por_placa",
                        lambda placa: [vendida, dict(MOTO_SALIENTE)])
    inventario.registrar_permuta(formulario(), 3, "Encargado")
    assert entorno[0][0] == 50


def test_datos_invalidos_de_la_entrante_no_registran(entorno):
    with pytest.raises(ErrorValidacion):
        inventario.registrar_permuta(formulario(marca=""), 3, "Encargado")
    assert entorno == []


# ------------------------------------------------------------
#  RUNT de la moto que entra
# ------------------------------------------------------------

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
"""


def test_con_runt_guarda_los_datos_de_contrato_en_la_misma_llamada(entorno):
    inventario.registrar_permuta(formulario(texto_runt=RUNT_ENTRANTE), 3, "Encargado")
    datos_contrato = entorno[0][6]
    assert datos_contrato["placa"] == "ABC123"
    assert datos_contrato["numero_motor"] == "G3S8E0123456"
    # Registro completo: lo que el RUNT no trae va en None.
    assert set(datos_contrato) == set(contratos.COLUMNAS)
    assert datos_contrato["numero_vin"] is None


def test_runt_de_otra_placa_no_registra(entorno):
    with pytest.raises(ErrorValidacion, match="no coincide"):
        inventario.registrar_permuta(
            formulario(texto_runt=RUNT_ENTRANTE, placa="QQQ111"), 3, "Encargado")
    assert entorno == []


def test_runt_ilegible_no_registra(entorno):
    with pytest.raises(ErrorValidacion, match="RUNT"):
        inventario.registrar_permuta(
            formulario(texto_runt="esto no es una consulta"), 3, "Encargado")
    assert entorno == []


def test_prellenar_toma_la_moto_del_runt_y_conserva_lo_escrito():
    form = ImmutableMultiDict({
        "texto_runt": RUNT_ENTRANTE, "placa_saliente": "XYZ987",
        "asesor_id": "7", "precio": "8500000", "marca": "otra",
    })
    valores = inventario.prellenar_permuta_desde_runt(form)
    assert valores["marca"] == "YAMAHA"          # el RUNT pisa lo que trae
    assert valores["modelo"] == "FZ 2.0"         # LINEA del RUNT -> modelo
    assert valores["anio"] == "2020"             # MODELO del RUNT -> año
    assert valores["cilindraje"] == "149"
    assert valores["placa"] == "ABC123"
    assert valores["placa_saliente"] == "XYZ987"  # lo ya escrito se conserva
    assert valores["asesor_id"] == "7"
    assert valores["precio"] == "8500000"
    assert valores["texto_runt"] == RUNT_ENTRANTE


def test_prellenar_sin_runt_avisa():
    with pytest.raises(ErrorValidacion, match="Pegue"):
        inventario.prellenar_permuta_desde_runt(ImmutableMultiDict({"texto_runt": "  "}))


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

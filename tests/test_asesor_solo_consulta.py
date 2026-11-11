"""
El asesor consulta el inventario pero no registra operaciones desde el
panel: ni ventas ("Vendida" en la tarjeta) ni compras. En el detalle de
una moto de su sede ve los datos del RUNT, sin poder cargarlos.

No tocan la base: servicios y repositorio se reemplazan con monkeypatch.
Correr desde la raíz:  python -m pytest tests/
"""

from pathlib import Path

import pytest
from flask import Flask

from app.servicios import busqueda, contratos, inventario

RAIZ = Path(__file__).resolve().parent.parent
ASESOR = 10
MOTO = {"id": 5, "marca": "Yamaha", "modelo": "FZ", "anio": 2019, "precio": 7500000,
        "placa": "ABC12D", "estado": "disponible", "sede_id": 1, "kilometraje": 20000,
        "sedes": {"nombre": "Sede Norte"}}
RUNT = {"placa": "ABC12D", "numero_motor": "MOTOR-123", "numero_chasis": "CHASIS-456",
        # Columnas que la fila trae pero la ficha no muestra (no están en
        # ETIQUETAS_VISIBLES): el dueño anterior no es dato para el asesor.
        "propietario_nombre": "Pedro Dueno", "propietario_documento": "1020304050"}


@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth.routes import auth_bp
    from app.publico.routes import publico_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True, VAPID_PUBLIC_KEY="BVapidPublicaDePrueba")
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.jinja_env.filters["pesos"] = lambda v: "" if v is None else f"{v:,.0f}".replace(",", ".")
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(publico_bp)
    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    return app


def cliente(app, rol, sede_id=1):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logueado=True, rol=rol, sede_id=sede_id,
                 usuario_id=ASESOR, usuario_nombre="Luis Gomez")
    return c


# ------------------------------------------------------------
# Ventas: el asesor no las registra
# ------------------------------------------------------------

def test_el_asesor_no_entra_a_registrar_una_venta(app, monkeypatch):
    monkeypatch.setattr(inventario, "moto_para_vender",
                        lambda _id: pytest.fail("el rol se rechaza antes de mirar la moto"))
    monkeypatch.setattr(inventario, "vender_moto",
                        lambda *a, **k: pytest.fail("un asesor no registra ventas"))
    c = cliente(app, "asesor")
    assert c.get("/admin/vender/5").status_code == 403
    assert c.post("/admin/vender/5", data={"asesor_id": ASESOR}).status_code == 403


@pytest.mark.parametrize("rol", ["admin", "gerencia", "encargado_sede"])
def test_quien_registra_la_venta_elige_al_asesor(app, monkeypatch, rol):
    llamadas = []
    monkeypatch.setattr(inventario, "moto_para_vender", lambda _id: MOTO)
    monkeypatch.setattr(inventario, "asesores_para_venta",
                        lambda _moto: [{"id": 21, "nombre_completo": "Ana Asesora"}])
    monkeypatch.setattr(inventario, "vender_moto",
                        lambda *args: llamadas.append(args) or 900)
    c = cliente(app, rol)
    html = c.get("/admin/vender/5").get_data(as_text=True)
    assert "¿Qué asesor la vendió?" in html and "Ana Asesora" in html

    respuesta = c.post("/admin/vender/5", data={"asesor_id": "21", "usuario_id": "99"})
    assert respuesta.headers["Location"].endswith("/admin/ventas")
    # (moto, quién registra: de la sesión, asesor: del formulario)
    assert llamadas == [(5, ASESOR, "Luis Gomez", "21")]


def test_la_tarjeta_del_inventario_no_le_ofrece_vendida_al_asesor(app, monkeypatch):
    monkeypatch.setattr(busqueda, "buscar", lambda _args: {
        "motos": [MOTO], "sedes": [{"id": 1, "nombre": "Sede Norte"}],
        "filtros": {"id": "", "placa": "", "estado": "", "sede": ""}})
    asesor = cliente(app, "asesor").get("/admin/").get_data(as_text=True)
    assert "ABC12D" in asesor and "/admin/moto/5" in asesor
    assert "/admin/vender/5" not in asesor and "Vendida</a>" not in asesor
    assert "/admin/comprar" not in asesor
    encargado = cliente(app, "encargado_sede").get("/admin/").get_data(as_text=True)
    assert "/admin/vender/5" in encargado


# ------------------------------------------------------------
# Detalle: el asesor ve el RUNT, no lo carga
# ------------------------------------------------------------

@pytest.fixture
def detalle(monkeypatch):
    """La moto 5 es de la sede 1. Devuelve un dict para cambiar lo que hay cargado."""
    from flask import session

    estado = {"runt": RUNT}
    monkeypatch.setattr(inventario, "obtener_moto_admin", lambda _id: MOTO)
    monkeypatch.setattr(inventario, "obtener_galeria", lambda _id: [])
    monkeypatch.setattr(contratos, "moto_en_alcance",
                        lambda _id: MOTO if session.get("rol") in ("admin", "gerencia")
                        or session.get("sede_id") == MOTO["sede_id"] else None)
    monkeypatch.setattr(contratos, "obtener_datos", lambda _id: estado["runt"])
    return estado


def test_el_asesor_ve_los_datos_del_runt_pero_no_puede_cargarlos(app, detalle):
    html = cliente(app, "asesor").get("/admin/moto/5").get_data(as_text=True)
    assert 'id="datos-contrato"' in html
    assert "MOTOR-123" in html and "CHASIS-456" in html
    assert 'name="texto_runt"' not in html and "/admin/moto/5/datos-contrato" not in html
    assert "Reemplazar datos de contrato" not in html
    # Solo las columnas declaradas visibles: nada del dueño anterior.
    assert "Pedro Dueno" not in html and "1020304050" not in html


def test_si_no_hay_runt_cargado_el_asesor_lo_sabe(app, detalle):
    detalle["runt"] = None
    html = cliente(app, "asesor").get("/admin/moto/5").get_data(as_text=True)
    assert "aún no tiene los datos del RUNT cargados" in html
    assert 'name="texto_runt"' not in html


def test_el_asesor_no_ve_el_runt_de_una_moto_de_otra_sede(app, detalle):
    html = cliente(app, "asesor", sede_id=2).get("/admin/moto/5").get_data(as_text=True)
    assert 'id="datos-contrato"' not in html and "MOTOR-123" not in html


def test_el_encargado_sigue_viendo_y_cargando_el_runt(app, detalle):
    html = cliente(app, "encargado_sede").get("/admin/moto/5").get_data(as_text=True)
    assert "MOTOR-123" in html and 'name="texto_runt"' in html


def test_el_asesor_no_puede_guardar_datos_de_contrato(app, monkeypatch):
    monkeypatch.setattr(contratos, "procesar_y_guardar",
                        lambda *a, **k: pytest.fail("el asesor no carga el RUNT"))
    respuesta = cliente(app, "asesor").post("/admin/moto/5/datos-contrato",
                                            data={"texto_runt": "PLACA: ABC12D"})
    assert respuesta.status_code == 403

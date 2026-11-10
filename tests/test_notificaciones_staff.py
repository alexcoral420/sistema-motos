"""
Pruebas de la suscripción push del staff (Fase B1):
POST /admin/gerencia/activar-notificaciones -> notificaciones_staff ->
repositorios.guardar_dispositivo_staff (tabla dispositivos_staff, 027).

No tocan la base: el cliente de Supabase se reemplaza por uno falso que
registra las llamadas. Correr desde la raíz:  python -m pytest tests/
"""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, redirect
from postgrest.exceptions import APIError

from app.db import repositorios
from app.servicios import reportes

RAIZ = Path(__file__).resolve().parent.parent
URL = "/admin/gerencia/activar-notificaciones"
USUARIO_SESION = 42


def b64url(crudo: bytes) -> str:
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


SUSCRIPCION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": b64url(b"\x04" + b"k" * 64), "auth": b64url(b"a" * 16)},
}


class ConsultaFalsa:
    def __init__(self, llamadas, tabla):
        self.llamadas, self.tabla = llamadas, tabla

    def upsert(self, fila, on_conflict=None):
        self.llamadas.append({"tabla": self.tabla, "fila": fila, "on_conflict": on_conflict})
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": 1}])


@pytest.fixture
def llamadas(monkeypatch):
    """Upserts que llegan a Supabase (cliente admin falso)."""
    registro = []
    cliente = SimpleNamespace(table=lambda nombre: ConsultaFalsa(registro, nombre))
    monkeypatch.setattr(repositorios, "get_supabase_admin", lambda: cliente)
    return registro


@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth.routes import auth_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True, VAPID_PUBLIC_KEY="BVapidPublicaDePrueba")
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.jinja_env.filters["pesos"] = lambda v: "" if v is None else f"{v:,.0f}".replace(",", ".")
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_bp)
    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    return app


def cliente_con_rol(app, rol):
    cliente = app.test_client()
    if rol:
        with cliente.session_transaction() as s:
            s.update(logueado=True, rol=rol, sede_id=1,
                     usuario_id=USUARIO_SESION, usuario_nombre="Prueba")
    return cliente


# ------------------------------------------------------------
#  Rol
# ------------------------------------------------------------

@pytest.mark.parametrize("rol", ["gerencia", "admin"])
def test_gerencia_y_admin_pueden_activar(app, llamadas, rol):
    respuesta = cliente_con_rol(app, rol).post(URL, json={"suscripcion": SUSCRIPCION})
    assert respuesta.status_code == 200 and respuesta.get_json() == {"ok": True}
    assert len(llamadas) == 1


@pytest.mark.parametrize("rol", ["asesor", "encargado_sede"])
def test_otros_roles_reciben_403_y_no_se_guarda_nada(app, llamadas, rol):
    respuesta = cliente_con_rol(app, rol).post(URL, json={"suscripcion": SUSCRIPCION})
    assert respuesta.status_code == 403
    assert llamadas == []


def test_sin_sesion_va_al_login(app, llamadas):
    respuesta = cliente_con_rol(app, None).post(URL, json={"suscripcion": SUSCRIPCION})
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/login")
    assert llamadas == []


def test_usuario_deshabilitado_no_guarda(app, llamadas, monkeypatch):
    from app.admin import routes as admin_routes
    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: redirect("/login"))

    respuesta = cliente_con_rol(app, "gerencia").post(URL, json={"suscripcion": SUSCRIPCION})
    assert respuesta.status_code == 302
    assert llamadas == []


# ------------------------------------------------------------
#  Identidad y validación
# ------------------------------------------------------------

def test_usuario_id_sale_de_la_sesion_no_del_cuerpo(app, llamadas):
    cliente_con_rol(app, "gerencia").post(
        URL, json={"suscripcion": SUSCRIPCION, "usuario_id": 999})

    assert llamadas[0]["tabla"] == "dispositivos_staff"
    assert llamadas[0]["fila"]["usuario_id"] == USUARIO_SESION


def test_la_suscripcion_se_reconstruye_sin_campos_extra(app, llamadas):
    colada = {**SUSCRIPCION, "expirationTime": None, "extra": "x",
              "keys": {**SUSCRIPCION["keys"], "otra": "y"}}
    cliente_con_rol(app, "gerencia").post(URL, json={"suscripcion": colada})
    assert llamadas[0]["fila"]["suscripcion"] == SUSCRIPCION


@pytest.mark.parametrize("cuerpo", [
    None,
    {"suscripcion": "texto"},
    {"suscripcion": {**SUSCRIPCION, "endpoint": "https://interno.local/push"}},   # SSRF
    {"suscripcion": {**SUSCRIPCION, "endpoint": "http://fcm.googleapis.com/x"}},  # sin https
    {"suscripcion": {**SUSCRIPCION, "keys": {"p256dh": "corta", "auth": "x"}}},
])
def test_suscripcion_invalida_da_400_y_no_guarda(app, llamadas, cuerpo):
    respuesta = cliente_con_rol(app, "gerencia").post(URL, json=cuerpo)
    assert respuesta.status_code == 400 and "error" in respuesta.get_json()
    assert llamadas == []


def test_error_de_la_base_da_500_con_mensaje(app, monkeypatch):
    def falla(usuario_id, suscripcion):
        raise APIError({"message": "x", "code": "23503"})
    monkeypatch.setattr(repositorios, "guardar_dispositivo_staff", falla)

    respuesta = cliente_con_rol(app, "gerencia").post(URL, json={"suscripcion": SUSCRIPCION})
    assert respuesta.status_code == 500 and "error" in respuesta.get_json()


# ------------------------------------------------------------
#  Idempotencia
# ------------------------------------------------------------

def test_mismo_endpoint_dos_veces_hace_el_mismo_upsert_y_reactiva(app, llamadas):
    """
    La deduplicación real la hace UNIQUE (usuario_id, endpoint) en la base;
    aquí se verifica que el código siempre se apoya en ella (upsert con ese
    on_conflict, nunca insert) y que reactiva la fila (activo = true).
    """
    cliente = cliente_con_rol(app, "gerencia")
    for _ in range(2):
        assert cliente.post(URL, json={"suscripcion": SUSCRIPCION}).status_code == 200

    esperado = {"tabla": "dispositivos_staff",
                "fila": {"usuario_id": USUARIO_SESION, "suscripcion": SUSCRIPCION, "activo": True},
                "on_conflict": "usuario_id,endpoint"}
    assert llamadas == [esperado, esperado]


# ------------------------------------------------------------
#  Botón en el panel
# ------------------------------------------------------------

def test_el_panel_de_gerencia_muestra_el_boton(app, monkeypatch):
    resumen = {**reportes.agregar_resumen([], [], []), "periodo": "Del x al y"}
    monkeypatch.setattr(reportes, "resumen_semanal", lambda desde, hasta: resumen)

    html = cliente_con_rol(app, "gerencia").get("/admin/gerencia/resumen-semanal").get_data(as_text=True)

    assert 'id="btn-notif"' in html
    assert URL in html and '"BVapidPublicaDePrueba"' in html
    assert "suscribir-push.js" in html and "serviceWorker.register('/sw.js')" in html

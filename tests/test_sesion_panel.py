"""
Pruebas de la duración de la sesión del panel: 10 días desde el login.

No tocan la base: autenticar y el repositorio se reemplazan con
monkeypatch. Correr desde la raíz:  python -m pytest tests/
"""

import time
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask, session

from app.auth import sesion
from app.db import repositorios
from config import Config

RAIZ = Path(__file__).resolve().parent.parent
DIA = 24 * 60 * 60
USUARIO = {"id": 10, "usuario": "luis", "nombre_completo": "Luis Gomez", "rol": "asesor",
           "sede_id": 1, "whatsapp": None, "activo": True, "puede_ingresar": True}


@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth import routes as auth_routes
    from app.publico.routes import publico_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True, RATELIMIT_ENABLED=False,
                      PERMANENT_SESSION_LIFETIME=Config.PERMANENT_SESSION_LIFETIME)
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(publico_bp)
    monkeypatch.setattr(auth_routes, "autenticar", lambda u, p: dict(USUARIO))
    monkeypatch.setattr(repositorios, "obtener_usuario_por_id", lambda _id: dict(USUARIO))
    # Las páginas que se visitan no deben llegar a la base.
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja", lambda _id: None)
    monkeypatch.setattr(repositorios, "listar_leads_bandeja", lambda asesor_id=None: [])
    return app


def entrar(app):
    c = app.test_client()
    respuesta = c.post("/login", data={"usuario": "luis", "password": "x"})
    return c, respuesta


def test_la_sesion_del_panel_dura_diez_dias():
    assert Config.DIAS_SESION_PANEL == 10
    assert Config.PERMANENT_SESSION_LIFETIME == timedelta(days=10)


def test_el_login_deja_una_cookie_que_sobrevive_al_cierre_del_navegador(app):
    c, respuesta = entrar(app)
    cookie = respuesta.headers["Set-Cookie"]
    assert "Expires=" in cookie                 # una cookie de sesión no trae Expires
    with c.session_transaction() as s:
        assert s.permanent is True
        assert abs(s["panel_ingreso"] - time.time()) < 5


@pytest.mark.parametrize("dias, vencida", [(0, False), (9, False), (9.9, False), (10.1, True), (40, True)])
def test_tope_de_diez_dias_desde_el_login(app, dias, vencida):
    with app.test_request_context("/admin/"):
        session["panel_ingreso"] = int(time.time() - dias * DIA)
        assert sesion.sesion_vencida() is vencida


def test_sesion_anterior_al_cambio_no_se_cierra_y_empieza_a_contar(app):
    with app.test_request_context("/admin/"):
        assert sesion.sesion_vencida() is False
        assert abs(session["panel_ingreso"] - time.time()) < 5


def test_pasados_diez_dias_el_panel_manda_al_login_y_borra_la_identidad(app):
    c, _ = entrar(app)
    with c.session_transaction() as s:
        s["panel_ingreso"] = int(time.time() - 11 * DIA)
        s["leads_chat_firmas"] = ["3001234567|"]        # del sitio público: no se toca

    respuesta = c.get("/admin/leads")
    assert respuesta.status_code == 302 and "/login" in respuesta.headers["Location"]
    with c.session_transaction() as s:
        assert "logueado" not in s and "usuario_id" not in s and "panel_ingreso" not in s
        assert s.permanent is False
        assert s["leads_chat_firmas"] == ["3001234567|"]


def test_usar_el_panel_no_alarga_el_tope(app):
    c, _ = entrar(app)
    with c.session_transaction() as s:
        s["panel_ingreso"] = int(time.time() - 9 * DIA)
        ingreso = s["panel_ingreso"]
    assert c.get("/admin/leads/999999").status_code == 302      # petición normal, con sesión
    with c.session_transaction() as s:
        assert s.get("logueado") is True
        assert s["panel_ingreso"] == ingreso


def test_salir_deja_la_cookie_como_de_navegador(app):
    c, _ = entrar(app)
    c.get("/logout")
    with c.session_transaction() as s:
        assert s.permanent is False and "panel_ingreso" not in s


def test_quitar_el_acceso_sigue_teniendo_efecto_inmediato(app, monkeypatch):
    c, _ = entrar(app)
    monkeypatch.setattr(repositorios, "obtener_usuario_por_id",
                        lambda _id: dict(USUARIO, puede_ingresar=False))
    respuesta = c.get("/admin/leads")
    assert "/login" in respuesta.headers["Location"]
    with c.session_transaction() as s:
        assert "logueado" not in s

"""
La integración con Meta/Twilio se quitó: ni /webhook ni POST /api/mensajes
existen. Estas pruebas evitan que vuelvan a registrarse por descuido.

No tocan Supabase: solo miran el mapa de rutas y piden rutas que no existen.
"""
import pytest

from app import create_app
from app.seguridad.limites import limiter


@pytest.fixture(scope="module")
def app():
    app = create_app()
    # create_app conecta el limiter GLOBAL; desde ahí sus decoradores
    # limitarían también las apps mínimas de otros archivos de pruebas
    # (429 inesperados). Se deja apagado para el resto de la corrida.
    limiter.enabled = False
    return app


def test_no_hay_blueprint_webhook(app):
    assert "webhook" not in app.blueprints
    assert not [r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/webhook")]


def test_no_hay_ruta_de_mensajes_en_la_api(app):
    assert not [r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api/mensajes")]


@pytest.mark.parametrize("metodo, ruta", [
    ("get", "/webhook"),
    ("post", "/webhook"),
    ("post", "/api/mensajes"),
])
def test_las_rutas_quitadas_responden_404(app, metodo, ruta):
    respuesta = getattr(app.test_client(), metodo)(ruta)
    assert respuesta.status_code == 404


def test_config_sin_credenciales_de_meta_ni_twilio(app):
    for clave in ("VERIFY_TOKEN", "META_APP_SECRET", "WHATSAPP_TOKEN", "PHONE_NUMBER_ID",
                  "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_NUMBER"):
        assert clave not in app.config

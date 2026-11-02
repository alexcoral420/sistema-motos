"""
Tests de "Mi espacio" del motero: validación (servicio puro), el decorador
de sesión (con Supabase reemplazado por monkeypatch) y la regla de que el
blueprint del motero nunca arrastra el cliente service_role.
"""

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from flask import Flask, g, session
from supabase import AuthApiError

from app.motero import sesion as sesion_motero
from app.seguridad.cifrado import cifrar, descifrar
from app.seguridad.validadores import ErrorValidacion
from app.servicios import cuentas_motero


def _registro(**cambios):
    datos = {
        "nombre": "  Juan Pérez ",
        "email": " Juan@Correo.COM ",
        "telefono": "300 123-4567",
        "password": "clave-segura",
        "acepta_politica": "on",
    }
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not None}


# ---------- validación ----------

def test_registro_valido_limpia_datos():
    datos = cuentas_motero.validar_registro(_registro())
    assert datos == {
        "email": "juan@correo.com",
        "password": "clave-segura",
        "nombre": "Juan Pérez",
        "telefono": "3001234567",
    }


def test_registro_telefono_opcional():
    assert cuentas_motero.validar_registro(_registro(telefono=""))["telefono"] is None


@pytest.mark.parametrize("cambio, campo", [
    ({"acepta_politica": None}, "acepta_politica"),
    ({"acepta_politica": "off"}, "acepta_politica"),
    ({"email": "sin-arroba"}, "correo"),
    ({"email": "a@b"}, "correo"),
    ({"password": "corta"}, "password"),
    ({"password": "x" * 73}, "password"),
    ({"nombre": " "}, "nombre"),
    ({"telefono": "abc"}, "telefono"),
])
def test_registro_invalido(cambio, campo):
    with pytest.raises(ErrorValidacion) as e:
        cuentas_motero.validar_registro(_registro(**cambio))
    assert e.value.campo == campo


def test_metadata_lleva_consentimiento_para_el_trigger():
    datos = cuentas_motero.validar_registro(_registro())
    meta = cuentas_motero.metadata_registro(datos)
    assert meta["acepta_politica"] == "true"
    assert "password" not in meta and "email" not in meta


def test_ingreso_exige_password():
    with pytest.raises(ErrorValidacion):
        cuentas_motero.validar_ingreso({"email": "a@b.co", "password": ""})


@pytest.mark.parametrize("siguiente, esperado", [
    ("/mi-espacio", "/mi-espacio"),
    ("/mi-espacio?x=1", "/mi-espacio?x=1"),
    ("//evil.com", "/def"),
    ("/\\evil.com", "/def"),
    ("https://evil.com", "/def"),
    ("/a\r\nSet-Cookie: x", "/def"),
    (None, "/def"),
    ("", "/def"),
])
def test_destino_seguro(siguiente, esperado):
    assert cuentas_motero.destino_seguro(siguiente, "/def") == esperado


def test_necesita_refresco():
    ahora = 1_000_000
    assert cuentas_motero.necesita_refresco(ahora + 3600, ahora) is False
    assert cuentas_motero.necesita_refresco(ahora + 30, ahora) is True
    assert cuentas_motero.necesita_refresco(ahora - 5, ahora) is True
    assert cuentas_motero.necesita_refresco(None, ahora) is True


def test_mensaje_error_auth():
    assert "incorrectos" in cuentas_motero.mensaje_error_auth("invalid_credentials")
    assert cuentas_motero.mensaje_error_auth("algo_nuevo") == cuentas_motero.MENSAJE_ERROR_GENERICO
    assert cuentas_motero.mensaje_error_auth(None) == cuentas_motero.MENSAJE_ERROR_GENERICO


# ---------- decorador de sesión ----------

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test", CLAVE_CIFRADO=Fernet.generate_key())
    from app.motero.routes import motero_bp
    app.register_blueprint(motero_bp)
    return app


def _sesion_supabase(uid="u-1", access="access-1", refresh="refresh-1", expira=None):
    return SimpleNamespace(
        user=SimpleNamespace(id=uid, email="m@correo.com"),
        access_token=access, refresh_token=refresh,
        expires_at=expira if expira is not None else int(time.time()) + 3600,
    )


class _AuthFalso:
    def __init__(self, get_user=None, refresh=None):
        self._get_user, self._refresh = get_user, refresh
        self.refrescos = 0

    def get_user(self, jwt):
        return self._get_user(jwt)

    def refresh_session(self, token):
        self.refrescos += 1
        return self._refresh(token)


def _instalar_auth(monkeypatch, auth):
    monkeypatch.setattr(sesion_motero, "cliente_auth", lambda: SimpleNamespace(auth=auth))


def _rechazo(*_):
    raise AuthApiError("no", 401, "bad_jwt")


@sesion_motero.login_requerido_motero
def _vista_protegida():
    return "ok"


def test_sin_sesion_redirige_a_ingresar(app):
    with app.test_request_context("/mi-espacio"):
        respuesta = _vista_protegida()
        assert respuesta.status_code == 302
        assert "/ingresar?next=/mi-espacio" in respuesta.location


def test_token_vigente_pasa_y_deja_g_motero(app, monkeypatch):
    auth = _AuthFalso(get_user=lambda jwt: SimpleNamespace(user=SimpleNamespace(id="u-1")))
    _instalar_auth(monkeypatch, auth)
    with app.test_request_context("/mi-espacio"):
        sesion_motero.guardar_sesion_motero(_sesion_supabase())
        assert _vista_protegida() == "ok"
        assert g.motero["id"] == "u-1"
        assert g.motero["access_token"] == "access-1"
        assert auth.refrescos == 0


def test_tokens_quedan_cifrados_en_la_cookie(app):
    with app.test_request_context("/"):
        sesion_motero.guardar_sesion_motero(_sesion_supabase())
        assert session["motero_access"] != "access-1"
        assert descifrar(session["motero_access"]) == "access-1"
        assert descifrar(session["motero_refresh"]) == "refresh-1"


def test_token_por_vencer_se_refresca(app, monkeypatch):
    nueva = _sesion_supabase(access="access-2", refresh="refresh-2")
    auth = _AuthFalso(refresh=lambda t: SimpleNamespace(session=nueva, user=nueva.user))
    _instalar_auth(monkeypatch, auth)
    with app.test_request_context("/mi-espacio"):
        sesion_motero.guardar_sesion_motero(_sesion_supabase(expira=int(time.time()) + 10))
        assert _vista_protegida() == "ok"
        assert auth.refrescos == 1
        assert g.motero["access_token"] == "access-2"
        assert descifrar(session["motero_refresh"]) == "refresh-2"


def test_token_rechazado_intenta_refresco(app, monkeypatch):
    nueva = _sesion_supabase(access="access-2")
    auth = _AuthFalso(get_user=_rechazo,
                      refresh=lambda t: SimpleNamespace(session=nueva, user=nueva.user))
    _instalar_auth(monkeypatch, auth)
    with app.test_request_context("/mi-espacio"):
        sesion_motero.guardar_sesion_motero(_sesion_supabase())
        assert _vista_protegida() == "ok"
        assert auth.refrescos == 1


def test_refresco_rechazado_cierra_solo_la_sesion_del_motero(app, monkeypatch):
    _instalar_auth(monkeypatch, _AuthFalso(get_user=_rechazo, refresh=_rechazo))
    with app.test_request_context("/mi-espacio"):
        sesion_motero.guardar_sesion_motero(_sesion_supabase())
        session["logueado"] = True          # sesión del panel en la misma cookie
        session["visita_id"] = "abc"        # clave del sitio público
        respuesta = _vista_protegida()
        assert respuesta.status_code == 302
        assert not any(k in session for k in sesion_motero.CLAVES_SESION_MOTERO)
        assert session["logueado"] is True and session["visita_id"] == "abc"


def test_cookie_manipulada_no_da_sesion(app):
    with app.test_request_context("/mi-espacio"):
        session["motero_id"] = "u-1"
        session["motero_access"] = "texto-que-no-es-fernet"
        session["motero_refresh"] = cifrar("r")
        assert _vista_protegida().status_code == 302


# ---------- sesión del panel ----------

def test_cerrar_sesion_panel_no_toca_motero_ni_publico(app):
    from app.auth.sesion import CLAVES_SESION_PANEL, cerrar_sesion_panel
    with app.test_request_context("/"):
        for clave in CLAVES_SESION_PANEL:
            session[clave] = "x"
        session["motero_id"] = "u-1"
        session["asesor_origen"] = "7"
        cerrar_sesion_panel()
        assert not any(k in session for k in CLAVES_SESION_PANEL)
        assert session["motero_id"] == "u-1" and session["asesor_origen"] == "7"


# ---------- regla crítica: nada de service_role en el motero ----------

def test_blueprint_motero_no_arrastra_service_role():
    """
    Importa el blueprint en un proceso limpio y verifica que ni el módulo
    de clientes con service_role ni el repositorio del admin quedaron
    cargados, directa o transitivamente.
    """
    codigo = (
        "import sys, app.motero.routes;"
        "prohibidos = [m for m in ('app.db.cliente', 'app.db.repositorios') if m in sys.modules];"
        "print(','.join(prohibidos))"
    )
    raiz = Path(__file__).resolve().parents[1]
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=raiz,
                            capture_output=True, text=True, check=True)
    assert salida.stdout.strip() == "", f"El blueprint del motero importa: {salida.stdout.strip()}"

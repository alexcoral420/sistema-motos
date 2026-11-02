"""
Sesión del motero: tokens de Supabase Auth guardados en la sesión de Flask.

La sesión de Flask de este proyecto es una cookie firmada (no cifrada) en
el navegador: httpOnly, Secure en producción, SameSite=Lax. Los tokens se
guardan además CIFRADOS con Fernet (CLAVE_CIFRADO): quien se lleve la
cookie no puede sacar de ella un JWT para ir directo contra Supabase; solo
podría usarla a través de este servidor, con su rate limit.

Las claves llevan prefijo motero_ y se borran solo ellas: la cookie la
comparten el panel (ver app/auth/sesion.CLAVES_SESION_PANEL) y el sitio
público, y salir de una no debe cerrar la otra.
"""

import time
from functools import wraps

from flask import g, redirect, request, session, url_for
from supabase import AuthApiError

from app.motero.cliente import cliente_auth
from app.seguridad.cifrado import cifrar, descifrar
from app.seguridad.logging_config import obtener_logger
from app.servicios.cuentas_motero import necesita_refresco

CLAVES_SESION_MOTERO = (
    "motero_id",
    "motero_email",
    "motero_access",    # cifrado
    "motero_refresh",   # cifrado
    "motero_expira",    # epoch en segundos del access token
)


def guardar_sesion_motero(sesion_supabase):
    """Guarda en la cookie la sesión que devolvió Supabase Auth (login o refresh)."""
    usuario = sesion_supabase.user
    session["motero_id"] = usuario.id
    session["motero_email"] = usuario.email
    session["motero_access"] = cifrar(sesion_supabase.access_token)
    session["motero_refresh"] = cifrar(sesion_supabase.refresh_token)
    session["motero_expira"] = sesion_supabase.expires_at


def cerrar_sesion_motero():
    for clave in CLAVES_SESION_MOTERO:
        session.pop(clave, None)


def tokens_motero():
    """(access_token, refresh_token) en claro, o (None, None) si no hay o no descifran."""
    access = descifrar(session.get("motero_access"))
    refresh = descifrar(session.get("motero_refresh"))
    if not access or not refresh:
        return None, None
    return access, refresh


def _refrescar(refresh_token) -> bool:
    """
    Pide un par de tokens nuevo. False si Supabase lo rechaza (refresh
    vencido, revocado o ya usado): la sesión no se puede recuperar.
    Un error de red no se traga: sube y la petición falla, sin cerrar la
    sesión por algo pasajero.
    """
    try:
        respuesta = cliente_auth().auth.refresh_session(refresh_token)
    except AuthApiError:
        return False
    if not respuesta or not respuesta.session or not respuesta.user:
        return False
    if respuesta.user.id != session.get("motero_id"):
        return False
    guardar_sesion_motero(respuesta.session)
    return True


def _token_valido(access_token) -> bool:
    """Supabase Auth confirma que el JWT es suyo, no venció y su sesión sigue viva."""
    try:
        respuesta = cliente_auth().auth.get_user(access_token)
    except AuthApiError:
        return False
    return bool(respuesta and respuesta.user and respuesta.user.id == session.get("motero_id"))


def _a_ingresar():
    cerrar_sesion_motero()
    return redirect(url_for("motero.ingresar", next=request.path))


def login_requerido_motero(f):
    """
    Protege una ruta del motero. Valida el access token contra Supabase
    Auth; si venció (o está por vencer) lo refresca y actualiza la sesión.
    Si no hay forma de recuperarla, limpia la sesión y manda a /ingresar.
    Deja en g.motero el id y email del motero de esta petición.
    """
    @wraps(f)
    def envoltura(*args, **kwargs):
        access, refresh = tokens_motero()
        if not access:
            return _a_ingresar()

        if necesita_refresco(session.get("motero_expira"), time.time()):
            valido = _refrescar(refresh)
        else:
            valido = _token_valido(access) or _refrescar(refresh)

        if not valido:
            obtener_logger().info(
                "Sesión de motero cerrada (token no recuperable): %s", session.get("motero_id"))
            return _a_ingresar()

        g.motero = {
            "id": session["motero_id"],
            "email": session.get("motero_email"),
            "access_token": tokens_motero()[0],
        }
        return f(*args, **kwargs)
    return envoltura

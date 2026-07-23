"""
Decoradores de autorización.

Un decorador es una función que "envuelve" a otra para añadirle
comportamiento sin modificar su código. @requiere_login envuelve una
ruta y, antes de dejarla ejecutar, comprueba que haya sesión iniciada.
Si no la hay, redirige al login.

Es el mismo requiere_login de tu app.py viejo, pero ahora vive aquí,
separado, para poder aplicarlo a cualquier ruta o blueprint que lo
necesite (sobre todo, a todo el panel de admin de una sola vez).
"""

from functools import wraps
from flask import session, redirect, url_for, abort



def requiere_rol(*roles_permitidos):
    """
    Restringe una ruta a ciertos roles.

    Uso:
        @requiere_rol("admin")              -> solo admin
        @requiere_rol("admin", "asesor")    -> admin o asesor

    Si el usuario no tiene sesión -> al login.
    Si tiene sesión pero su rol no está permitido -> 403 (prohibido).

    La diferencia entre 401 y 403 importa:
      - sin sesión = "no sé quién eres" -> te mando a identificarte
      - rol insuficiente = "sé quién eres, pero no puedes" -> 403
    """
    def decorador(func):
        @wraps(func)
        def envoltura(*args, **kwargs):
            if "logueado" not in session:
                return redirect(url_for("auth.login"))
            if session.get("rol") not in roles_permitidos:
                # Registramos el intento: un asesor tratando de entrar a una
                # ruta de admin es justo lo que la auditoría debe capturar.
                from app.seguridad.logging_config import obtener_logger
                obtener_logger().warning(
                    "Acceso denegado: usuario '%s' (rol %s) intentó una acción de %s.",
                    session.get("usuario_nombre"), session.get("rol"), roles_permitidos)
                abort(403)
            return func(*args, **kwargs)
        return envoltura
    return decorador

def requiere_login(f):
    """
    Protege una ruta: solo se ejecuta si hay sesión iniciada.

    Uso:
        @admin_bp.route("/agregar")
        @requiere_login
        def agregar():
            ...

    Si "logueado" no está en la sesión, redirige a la página de login.
    """
    @wraps(f)
    def decorada(*args, **kwargs):
        if "logueado" not in session:
            # No hay sesión -> al login. url_for("auth.login") apunta a
            # la función login() del blueprint "auth" que haremos ahora.
            return redirect(url_for("auth.login"))
        # Sí hay sesión -> ejecuta la ruta normalmente.
        return f(*args, **kwargs)
    return decorada
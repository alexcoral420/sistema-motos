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
from flask import session, redirect, url_for


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
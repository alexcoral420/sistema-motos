"""
Chequeo por petición de la sesión del panel.

El login valida al usuario UNA vez; sin este chequeo, quitarle el
acceso (o desactivarlo, o cambiarle el rol/sede) no tendría efecto
hasta que la sesión expire. Aquí se vuelve a consultar la base en cada
petición del panel: la base manda, la cookie no.
"""

from flask import session, redirect, url_for, request

from app.seguridad.logging_config import obtener_logger


# Claves de la sesión que pertenecen al panel. La cookie de sesión es una
# sola y la comparten el panel, el sitio público (asesor_origen, visita_id,
# leads_chat_firmas) y el motero (motero_*); por eso el panel borra SOLO lo
# suyo al entrar o salir, en vez de session.clear(). Si se agrega una clave
# del panel en el login, va también aquí.
CLAVES_SESION_PANEL = (
    "logueado",
    "usuario_id",
    "usuario_nombre",
    "rol",
    "sede_id",
    "whatsapp",
    # A dónde volver tras el login (app/auth/destino.py). Se guarda antes
    # de que haya sesión; el login la lee y la quita.
    "panel_destino",
)


def cerrar_sesion_panel():
    """Quita de la sesión la identidad del panel y nada más."""
    for clave in CLAVES_SESION_PANEL:
        session.pop(clave, None)


def verificar_usuario_habilitado():
    """
    Devuelve una redirección al login si el usuario en sesión ya no
    puede entrar (no existe, activo = false o puede_ingresar = false),
    limpiando la sesión. Si sigue habilitado, refresca rol y sede desde
    la base y devuelve None (la petición sigue).

    Sin usuario_id en sesión no hace nada: eso lo maneja el
    before_request que exige sesión.
    """
    usuario_id = session.get("usuario_id")
    if usuario_id is None:
        return None

    from app.db import repositorios   # import local: evita el ciclo de imports

    usuario = repositorios.obtener_usuario_por_id(usuario_id)
    if not usuario or not usuario.get("activo") or not usuario.get("puede_ingresar"):
        obtener_logger().warning(
            "Sesión cerrada: usuario '%s' (id %s) ya no está habilitado "
            "(existe=%s, activo=%s, puede_ingresar=%s). Ruta: %s",
            session.get("usuario_nombre"), usuario_id, bool(usuario),
            usuario.get("activo") if usuario else None,
            usuario.get("puede_ingresar") if usuario else None,
            request.path)
        cerrar_sesion_panel()
        return redirect(url_for("auth.login"))

    # Rol y sede salen de la base, no de lo que se guardó al hacer login.
    session["rol"] = usuario["rol"]
    session["sede_id"] = usuario["sede_id"]
    return None

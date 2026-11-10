"""
A dónde va un usuario del panel después de iniciar sesión.

Cada rol aterriza donde trabaja: gerencia en sus métricas, el asesor en
"Mi espacio", los demás en el inventario.

Excepción: quien llegó sin sesión a un lead del chat (lo normal al tocar
el aviso push con la app cerrada) vuelve a ese lead después del login.
El destino se guarda en la sesión, pero como sale de una URL que pudo
escribir cualquiera, solo se acepta si es exactamente una ruta de la
bandeja de leads: nunca se redirige a una dirección arbitraria.
"""

import re

from flask import session, url_for

CLAVE_DESTINO = "panel_destino"

# /admin/leads o /admin/leads/<id>. Nada más.
_DESTINO_PERMITIDO = re.compile(r"^/admin/leads(/\d{1,12})?$")


def recordar_destino(ruta):
    """Guarda la ruta pedida sin sesión, si es de la bandeja de leads."""
    if isinstance(ruta, str) and _DESTINO_PERMITIDO.match(ruta):
        session[CLAVE_DESTINO] = ruta


def destino_tras_login(rol, pendiente=None):
    """URL de llegada para ese rol; 'pendiente' es lo que guardó recordar_destino."""
    from app.servicios.leads_chat import ROLES_BANDEJA   # import local: evita el ciclo

    if (isinstance(pendiente, str) and _DESTINO_PERMITIDO.match(pendiente)
            and rol in ROLES_BANDEJA):
        return pendiente
    if rol == "gerencia":
        return url_for("admin.panel_gerencia")
    if rol == "asesor":
        return url_for("admin.espacio_asesor")
    return url_for("admin.index")

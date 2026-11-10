"""
Notificaciones push del staff (gerencia/admin).

Fase B1: solo la suscripción de cada navegador (tabla dispositivos_staff,
migración 027). El envío (B2) todavía no existe.

Es un sistema aparte de los dispositivos del motero (alertas_motero.py):
otra tabla, otro dueño (usuarios del panel, no perfiles de Supabase Auth)
y solo service_role la alcanza.
"""

from app.db import repositorios
from app.seguridad.suscripcion_push import validar_suscripcion
from app.seguridad.validadores import ErrorValidacion

# Quién puede activar notificaciones del panel. La ruta exige estos roles.
ROLES_NOTIFICACIONES = ("gerencia", "admin")


def activar_notificaciones(usuario_id: int, datos) -> None:
    """
    Valida el JSON de POST /admin/gerencia/activar-notificaciones
    ({"suscripcion": {...}}) y guarda la suscripción de ese navegador.

    usuario_id lo pasa la ruta desde la sesión; cualquier usuario_id que
    venga en 'datos' se ignora. La suscripción se reconstruye campo por
    campo (endpoint en la lista de servicios de push, claves con el largo
    correcto). Idempotente: el mismo navegador otra vez reactiva su fila.
    """
    if not isinstance(datos, dict):
        raise ErrorValidacion("La solicitud no es válida.")
    suscripcion = validar_suscripcion(datos.get("suscripcion"))
    repositorios.guardar_dispositivo_staff(usuario_id, suscripcion)

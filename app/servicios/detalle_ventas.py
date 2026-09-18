# servicios/detalle_ventas.py  (archivo nuevo)
"""
Módulo de detalle de ventas: el paso 2 que carga gerencia después de
la verificación (comprador, pagos, precio).

SEGURIDAD - AISLAMIENTO POR SEDE:
El panel usa get_supabase_admin(), que SALTA RLS. Por eso el aislamiento
por sede vive AQUÍ, en la app, y es la única muralla: si este filtro
falta en una consulta, no hay red debajo. Toda lectura de ventas del
módulo pasa por _sede_del_alcance().

Regla: fallar CERRADO. Un usuario mal configurado no ve nada, nunca
todo. El "ve todas las sedes" es explícito (solo gerencia/admin), no
un efecto colateral de un valor vacío.
"""

from flask import session
from app.db import repositorios

# Marcador explícito de "sin restricción de sede" (ve todas).
# Es un objeto único, imposible de confundir con un sede_id real ni
# con None. Que sea un valor propio y no None es a proposito: obliga
# a distinguir "ve todo" de "no se pudo determinar la sede".
TODAS_LAS_SEDES = object()


def _sede_del_alcance():
    """
    Decide qué sede puede ver el usuario en sesión. Tres resultados:

    - TODAS_LAS_SEDES  -> gerencia/admin: ve todas las sedes.
    - un sede_id (int) -> rol de sede: ve solo esa sede.
    - None             -> usuario mal configurado (rol de sede sin
                          sede asignada, o sin rol): NO VE NADA.

    La sede sale de la SESIÓN, nunca de un parámetro del request.
    """
    rol = session.get("rol")

    if rol in ("gerencia", "admin"):
        return TODAS_LAS_SEDES

    sede_id = session.get("sede_id")
    if sede_id is None:
        # Rol de sede sin sede: configuración inválida. Fallar cerrado.
        return None

    return sede_id


def listar_pendientes():
    """
    Ventas verificadas sin detalle, dentro del alcance del usuario.
    Si el usuario no tiene alcance válido, devuelve lista vacía.
    """
    alcance = _sede_del_alcance()

    if alcance is None:
        # Usuario mal configurado: no ve nada.
        return []

    if alcance is TODAS_LAS_SEDES:
        return repositorios.ventas_pendientes_detalle(sede_id=None)

    return repositorios.ventas_pendientes_detalle(sede_id=alcance)
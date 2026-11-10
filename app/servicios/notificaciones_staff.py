"""
Notificaciones push del staff (gerencia, admin y asesores).

  - Suscripción de cada navegador (tabla dispositivos_staff, migración 027).
  - Envío: aviso a los asesores cuando el chat registra un lead nuevo
    (avisar_lead_nuevo). Es el único aviso que existe por ahora.

Es un sistema aparte de los dispositivos del motero (alertas_motero.py):
otra tabla, otro dueño (usuarios del panel, no perfiles de Supabase Auth)
y solo service_role la alcanza.
"""

import threading

from app.db import repositorios
from app.seguridad.logging_config import obtener_logger
from app.seguridad.suscripcion_push import validar_suscripcion
from app.seguridad.validadores import ErrorValidacion

# Quién puede activar notificaciones del panel. La ruta exige estos roles.
ROLES_NOTIFICACIONES = ("gerencia", "admin", "asesor")

# A quién se le avisa un lead nuevo del chat: solo a los asesores. El
# primero que lo toma en la bandeja se lo queda.
ROL_AVISO_LEADS = "asesor"


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


def avisar_lead_nuevo(lead_id: int, contado: bool = False) -> dict:
    """
    Avisa por push a los asesores que entró un lead del chat.

    Destinatarios: los dispositivos activos de usuarios que AHORA tienen
    rol asesor y están activos (se resuelve al enviar, no al suscribir).

    El aviso no lleva ningún dato del cliente: pasa por los servidores de
    Google/Apple y aparece en la pantalla bloqueada. Lleva solo el enlace
    al lead, que exige sesión. 'contado' cambia el título: es la alerta de
    prioridad.

    Un 404/410 desactiva ese dispositivo. Devuelve el conteo
    {"enviados", "fallidos", "desactivados"}.
    """
    from app.servicios import push

    titulo = "Prioridad: compra de contado" if contado else "Nuevo lead del chat"
    cuerpo = "Un cliente dejó sus datos en el chat. Toque para tomarlo."
    url = f"/admin/leads/{lead_id}"
    conteo = {"enviados": 0, "fallidos": 0, "desactivados": 0}

    for dispositivo in repositorios.dispositivos_staff_por_rol(ROL_AVISO_LEADS):
        try:
            resultado = push.enviar_a_suscripcion(dispositivo["suscripcion"], titulo, cuerpo, url)
        except Exception as e:
            # Suscripción inválida, sin VAPID o error de red: se sigue con
            # los demás dispositivos.
            conteo["fallidos"] += 1
            obtener_logger().warning("Push de lead %s: dispositivo %s falló (%s)",
                                     lead_id, dispositivo.get("id"), type(e).__name__)
            continue

        if resultado["ok"]:
            conteo["enviados"] += 1
        elif push.suscripcion_muerta(resultado["estado"]):
            repositorios.desactivar_dispositivo_staff(dispositivo["id"])
            conteo["desactivados"] += 1
        else:
            conteo["fallidos"] += 1

    obtener_logger().info("Push de lead %s: %s", lead_id, conteo)
    return conteo


def _avisar_sin_fallar(lead_id, contado):
    try:
        avisar_lead_nuevo(lead_id, contado)
    except Exception as e:
        try:
            obtener_logger().error(f"Push de lead {lead_id}: no se pudo avisar ({e})")
        except Exception:
            pass


def avisar_lead_nuevo_en_segundo_plano(lead_id: int, contado: bool = False) -> None:
    """
    Lanza el aviso en un hilo: lo llama el chat justo después de guardar
    el lead, y el cliente no debe esperar a los servicios de push. Si el
    aviso falla, el lead igual queda en la bandeja.
    """
    threading.Thread(
        target=_avisar_sin_fallar, args=(lead_id, contado), daemon=True
    ).start()

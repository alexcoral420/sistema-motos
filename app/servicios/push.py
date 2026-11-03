"""
Envío Web Push: firma VAPID y POST al servicio de push. Sin base de datos.

Lo usan los dos sistemas que avisan por push, cada uno con su propia
reacción a una suscripción muerta:
  - recordatorios (anónimos, /recordatorio-soat): desactiva los
    recordatorios con ese endpoint.
  - alertas del motero (scripts/enviar_alertas.py): desactiva el
    dispositivo en `dispositivos`.
Por eso aquí solo se envía y se informa el estado; qué hacer con un
404/410 lo decide quien llama.
"""

import json

from pywebpush import WebPushException, webpush

from config import Config
from app.seguridad.suscripcion_push import validar_suscripcion

# Si el dispositivo está apagado, el servicio de push guarda el mensaje
# hasta TTL_PUSH segundos; pasado eso se descarta.
TTL_PUSH = 24 * 60 * 60
TIMEOUT_PUSH = 10
# Respuestas del servicio de push que significan "esta suscripción ya no
# existe" (el usuario revocó el permiso, desinstaló, limpió datos...).
ESTADOS_SUSCRIPCION_MUERTA = (404, 410)


def enviar_a_suscripcion(suscripcion, titulo: str, cuerpo: str, url: str = "/") -> dict:
    """
    Envía una notificación a una suscripción Web Push.

    Devuelve {"ok", "estado", "endpoint", "detalle"}; `endpoint` es el de la
    suscripción revalidada. Lanza ErrorValidacion si la suscripción no es
    válida (endpoint fuera de la lista, claves mal formadas), RuntimeError
    si falta la configuración VAPID, y deja pasar los errores de red
    (requests.RequestException).
    """
    if not (Config.VAPID_PRIVATE_KEY and Config.VAPID_SUBJECT):
        raise RuntimeError("Faltan VAPID_PRIVATE_KEY / VAPID_SUBJECT en el entorno.")

    # Se revalida aunque venga de la base: una fila escrita por fuera del
    # servicio no debe poder hacer que el servidor le pegue a cualquier URL.
    suscripcion = validar_suscripcion(suscripcion)
    payload = json.dumps({"title": titulo, "body": cuerpo, "url": url}, ensure_ascii=False)

    try:
        respuesta = webpush(
            subscription_info=suscripcion,
            data=payload,
            vapid_private_key=Config.VAPID_PRIVATE_KEY,
            # Dict nuevo en cada envío: pywebpush le agrega aud/exp.
            vapid_claims={"sub": Config.VAPID_SUBJECT},
            ttl=TTL_PUSH,
            timeout=TIMEOUT_PUSH,
        )
        return {"ok": True, "estado": getattr(respuesta, "status_code", None),
                "endpoint": suscripcion["endpoint"], "detalle": "enviado"}
    except WebPushException as e:
        return {"ok": False, "estado": e.status_code,
                "endpoint": suscripcion["endpoint"], "detalle": str(e)}


def suscripcion_muerta(estado) -> bool:
    return estado in ESTADOS_SUSCRIPCION_MUERTA

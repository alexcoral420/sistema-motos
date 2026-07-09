"""
Verificación de firmas del webhook (vulnerabilidad #2).

El webhook está abierto a internet: cualquiera puede enviarle un POST.
Para no procesar mensajes falsos, verificamos que cada petición venga
DE VERDAD de Twilio o de Meta, comprobando su firma criptográfica.

- Twilio firma con la cabecera 'X-Twilio-Signature'.
- Meta firma con la cabecera 'X-Hub-Signature-256'.

Si la firma no coincide, la petición es falsa y se rechaza antes de
tocar nada (ni base de datos, ni Claude).
"""

import hmac
import hashlib

from twilio.request_validator import RequestValidator

from config import Config


def verificar_firma_twilio(url: str, datos_form: dict, firma_recibida: str) -> bool:
    """
    Valida la firma de una petición de Twilio.

    Twilio provee un validador oficial: recalcula la firma a partir de
    la URL, los datos del formulario y tu AUTH_TOKEN, y la compara con
    la firma que llegó en la cabecera.

    url: la URL completa a la que Twilio hizo el POST.
    datos_form: los campos del formulario (request.form como dict).
    firma_recibida: el valor de la cabecera 'X-Twilio-Signature'.
    """
    if not firma_recibida:
        return False

    validador = RequestValidator(Config.TWILIO_AUTH_TOKEN)
    return validador.validate(url, datos_form, firma_recibida)


def verificar_firma_meta(cuerpo_bruto: bytes, firma_recibida: str) -> bool:
    """
    Valida la firma de una petición de Meta (WhatsApp Cloud API).

    Meta firma el cuerpo CRUDO de la petición con HMAC-SHA256, usando
    tu APP_SECRET. La cabecera llega como 'sha256=<firma>'. Recalculamos
    el HMAC del cuerpo y comparamos.

    cuerpo_bruto: request.get_data() -- los bytes EXACTOS recibidos.
    firma_recibida: el valor de la cabecera 'X-Hub-Signature-256'.
    """
    if not firma_recibida:
        return False

    # El secreto de la app de Meta. Lo añadiremos al .env como META_APP_SECRET.
    secreto = getattr(Config, "META_APP_SECRET", None)
    if not secreto:
        return False

    # La cabecera viene como "sha256=abc123...". Separamos el prefijo.
    if not firma_recibida.startswith("sha256="):
        return False
    firma_hex = firma_recibida.split("=", 1)[1]

    # Recalculamos el HMAC-SHA256 del cuerpo con nuestro secreto.
    esperado = hmac.new(
        secreto.encode("utf-8"),
        cuerpo_bruto,
        hashlib.sha256,
    ).hexdigest()

    # compare_digest compara de forma segura contra ataques de timing:
    # tarda lo mismo coincida o no, sin filtrar información por el tiempo.
    return hmac.compare_digest(esperado, firma_hex)
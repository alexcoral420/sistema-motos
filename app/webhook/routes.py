"""
Blueprint del webhook: la superficie expuesta a internet.

Dos rutas comparten la URL /webhook:
  - GET  -> verificación inicial de Meta (el "handshake" con VERIFY_TOKEN).
  - POST -> recepción de mensajes (de Twilio o de Meta).

PRINCIPIO CENTRAL (vulnerabilidad #2):
El POST verifica la FIRMA de la petición ANTES de procesar nada. Si la
firma no es válida -> 403 y fuera, sin tocar la base ni la IA. Fail-closed:
ante la duda, se rechaza. El portero está en la puerta, no adentro.

También aplicamos RATE LIMITING: un atacante no puede inundar el webhook
para saturarlo o disparar el gasto de la API (parte de la #3).
"""

from flask import Blueprint, request

from config import Config
from app.seguridad.limites import limiter
from app.webhook.verificacion import verificar_firma_twilio, verificar_firma_meta
from app.webhook.procesador import procesar_mensaje
from app.seguridad.logging_config import obtener_logger

webhook_bp = Blueprint("webhook", __name__)


@webhook_bp.route("/webhook", methods=["GET"])
def verificar():
    """
    Verificación inicial de Meta (WhatsApp Cloud API).

    Meta hace un GET con hub.mode, hub.verify_token y hub.challenge.
    Si el token coincide con el nuestro, devolvemos el challenge tal cual
    para confirmar que el webhook es nuestro. Si no, 403.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == Config.VERIFY_TOKEN:
        # Meta espera el challenge devuelto como texto plano.
        return challenge, 200

    # Token incorrecto: no es Meta o está mal configurado. Rechazamos.
    return "Token de verificación inválido", 403


@webhook_bp.route("/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def recibir():
    """
    Recepción de mensajes. Verifica la firma ANTES de procesar.

    Detecta el origen (Twilio manda form; Meta manda JSON), valida la
    firma correspondiente, y solo si es auténtica extrae el mensaje y
    llama al procesador.

    Nota profesional: siempre respondemos 200 al proveedor cuando la
    firma es válida, incluso si el procesamiento interno falló de forma
    controlada. Así el proveedor no reintenta en bucle. Lo ÚNICO que
    devuelve error es una firma inválida (403), que sí debe rechazarse.
    """
    content_type = request.content_type or ""

    # ─────────────────────────────────────────────────────────
    #  CAMINO META (JSON)
    # ─────────────────────────────────────────────────────────
    if "application/json" in content_type:
        # get_data() da los BYTES crudos, necesarios para el HMAC.
        # Debe leerse ANTES de parsear el JSON, sobre los bytes exactos.
        cuerpo_bruto = request.get_data()
        firma = request.headers.get("X-Hub-Signature-256", "")

        # >>> VERIFICACIÓN DE FIRMA (antes de procesar nada) <
        # >>> VERIFICACIÓN DE FIRMA (antes de procesar nada) <
        if not verificar_firma_meta(cuerpo_bruto, firma):
            log = obtener_logger()
            log.warning("Webhook: firma Meta inválida rechazada (posible intento no autenticado).")
            return "Firma inválida", 403

        # Firma válida: ahora sí parseamos el JSON de Meta.
        datos = request.get_json(silent=True) or {}
        numero, texto = _extraer_mensaje_meta(datos)

    # ─────────────────────────────────────────────────────────
    #  CAMINO TWILIO (form)
    # ─────────────────────────────────────────────────────────
    else:
        # url_for con _external nos da la URL completa que Twilio firmó.
        # Twilio incluye la URL exacta en el cálculo de la firma.
        url = request.url
        datos_form = request.form.to_dict()
        firma = request.headers.get("X-Twilio-Signature", "")

        # >>> VERIFICACIÓN DE FIRMA (antes de procesar nada) <
        # >>> VERIFICACIÓN DE FIRMA (antes de procesar nada) <
        if not verificar_firma_twilio(url, datos_form, firma):
            log = obtener_logger()
            log.warning("Webhook: firma Twilio inválida rechazada (posible intento no autenticado).")
            return "Firma inválida", 403

        numero = request.form.get("From", "").replace("whatsapp:", "")
        texto = request.form.get("Body", "")

    # ─────────────────────────────────────────────────────────
    #  PROCESAMIENTO (solo se llega aquí con firma válida)
    # ─────────────────────────────────────────────────────────
    procesar_mensaje(numero, texto)

    # Respondemos 200 pase lo que pase en el procesamiento interno:
    # la firma ya fue válida, el proveedor no debe reintentar.
    return "", 200


def _extraer_mensaje_meta(datos: dict):
    """
    Extrae (numero, texto) del JSON de Meta, tolerando formatos que no
    son mensajes de texto (estados de entrega, etc.) sin reventar.

    Devuelve (numero, texto) o (None, None) si no es un mensaje de texto.
    """
    try:
        valor = datos["entry"][0]["changes"][0]["value"]
        if "messages" not in valor:
            return None, None
        mensaje = valor["messages"][0]
        if mensaje.get("type") != "text":
            return None, None
        numero = mensaje["from"]
        texto = mensaje["text"]["body"]
        return numero, texto
    except (KeyError, IndexError, TypeError):
        # Estructura inesperada: no es un mensaje procesable. No es un
        # error nuestro; simplemente no hay nada que hacer.
        return None, None
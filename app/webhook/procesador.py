"""
Procesador del webhook: orquesta el flujo de un mensaje entrante.

Separa el "qué hacer con un mensaje" del "cómo se recibió por HTTP"
(eso último es trabajo del blueprint). Aquí llega un mensaje ya
extraído (número + texto) y se decide el flujo:
    registrar cliente -> guardar mensaje -> pedir respuesta a la IA
    -> guardar respuesta -> enviar.

>>> MODO PRUEBA <
No tocamos Supabase ni gastamos la API de Claude todavía. Cada paso
está simulado con prints o respuestas fijas, y marcado con el
comentario de la versión real para reactivarlo después.

PRINCIPIO DE SEGURIDAD (manejo de errores):
Un fallo interno (IA caída, base sin responder) NO debe propagarse
como un error hacia el proveedor (Twilio/Meta). Capturamos las
excepciones aquí y devolvemos un resultado controlado, para que la
ruta siempre pueda responder correctamente y el proveedor no reintente
en bucle. "Fallar de forma controlada", no "reventar".
"""

# Versiones reales (se reactivan al conectar base de datos e IA):
# from app.servicios import crm, ia, mensajeria
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger

def procesar_mensaje(numero: str, texto: str) -> dict:
    """
    Procesa un mensaje entrante ya extraído del webhook.

    numero: teléfono del cliente (sin el prefijo 'whatsapp:').
    texto: contenido del mensaje.

    Devuelve un dict con el resultado del procesamiento, por ejemplo:
        {"ok": True, "respuesta": "..."}      -> todo salió bien
        {"ok": False, "motivo": "..."}        -> hubo un fallo controlado

    NUNCA lanza una excepción hacia afuera: cualquier error se captura
    y se reporta en el dict de retorno. Así la ruta siempre responde
    limpio al proveedor.
    """
    # Validación mínima de entrada: sin número o sin texto, no hay nada
    # que procesar. Rechazo controlado (no es un error, es un no-op).
    # Validación de entrada externa (vulnerabilidad #6).
    # El webhook recibe datos de un bot, no de una persona: si algo llega
    # malformado, se descarta de forma controlada, sin procesar y sin
    # exponer errores. No hay "usuario" a quien mostrarle un mensaje.
    try:
        numero = validadores.validar_telefono(numero, "número")
        texto = validadores.validar_texto(
            texto, "texto", min_len=1, max_len=4000)
    except ErrorValidacion as e:
        # Mensaje inválido: lo registramos y lo descartamos.
        log = obtener_logger()
        log.warning("Webhook: mensaje descartado por validación (%s).", e.mensaje)
        return {"ok": False, "motivo": "entrada inválida"}
    try:
        # --- Paso 1: registrar/actualizar el cliente ---
        # Versión real:
        # cliente = crm.obtener_o_crear_cliente(numero)
        # conversacion = crm.crear_o_obtener_conversacion(cliente["id"])
        print(f"[PRUEBA] Cliente registrado: {numero}")

        # --- Paso 2: guardar el mensaje del cliente ---
        # Versión real:
        # mensaje = crm.registrar_mensaje(conversacion["id"], cliente["id"],
        #                                 tipo="cliente", contenido=texto)
        print(f"[PRUEBA] Mensaje del cliente guardado: {texto[:50]}")

        # --- Paso 3: pedir respuesta a la IA ---
        # Versión real:
        # respuesta = ia.respuesta_inteligente(texto)
        respuesta = f"[PRUEBA] Respuesta simulada de la IA para: {texto[:30]}"
        print(f"[PRUEBA] IA respondió: {respuesta[:50]}")

        # --- Paso 4: guardar la respuesta del bot ---
        # Versión real:
        # crm.registrar_mensaje(conversacion["id"], cliente["id"],
        #                       tipo="bot", contenido=respuesta)
        print("[PRUEBA] Respuesta del bot guardada")

        # --- Paso 5: enviar la respuesta al cliente ---
        # Versión real:
        # mensajeria.enviar_mensaje(numero, respuesta)
        print(f"[PRUEBA] Se enviaría a {numero}: {respuesta[:50]}")

        return {"ok": True, "respuesta": respuesta}

    except Exception as e:
        # Fallo controlado: lo registramos como ERROR pero NO lo dejamos
        # escapar. La ruta responderá "recibido" al proveedor igualmente,
        # evitando reintentos en bucle.
        log = obtener_logger()
        log.error("Webhook: error interno controlado (%s: %s).", type(e).__name__, e)
        return {"ok": False, "motivo": "error interno controlado"}
# app/servicios/historial_chat.py
# Validacion y firma del historial del chat web.
#
# POR QUE EXISTE:
# El navegador guarda la conversacion y la reenvia completa en cada
# mensaje. Eso incluye los mensajes del asistente, asi que sin control
# cualquiera podia inventarse un mensaje "del bot" (por ejemplo, la
# pregunta de autorizacion de datos) y el servidor lo daba por bueno.
#
# Aqui se cierra esa puerta sin guardar la conversacion en la base (lo que
# implicaria almacenar datos personales antes del consentimiento):
#   - Cada respuesta que el servidor emite sale FIRMADA (HMAC-SHA256 con
#     SECRET_KEY), atada al id de conversacion de la sesion y a su tipo.
#   - Al recibir el historial, todo mensaje "bot" sin firma valida se
#     descarta: ni llega al modelo ni cuenta para el consentimiento.
#
# La firma no encadena el historial anterior a proposito: el servidor
# recorta la conversacion con una ventana deslizante, y una cadena se
# romperia al recortar. Tampoco hace falta: reordenar mensajes propios y
# legitimos no le da a nadie nada que no pudiera escribir directamente.
#
# Modulo puro: no importa Flask ni la base. La clave y el id de
# conversacion llegan por parametro.

import hashlib
import hmac

from app.seguridad.validadores import ErrorValidacion


ROL_USUARIO = "usuario"
ROL_BOT = "bot"

# Tipo de un mensaje del asistente. "consentimiento" marca la pregunta de
# autorizacion de datos, que solo emite el servidor con texto fijo.
TIPO_NORMAL = "normal"
TIPO_CONSENTIMIENTO = "consentimiento"
TIPOS = (TIPO_NORMAL, TIPO_CONSENTIMIENTO)

# Limites de entrada. Cada mensaje viaja dos veces a Claude (asistente y
# extractor), asi que el tamano del historial es costo directo.
MAX_CARACTERES_USUARIO = 500
MAX_CARACTERES_BOT = 4000
MAX_MENSAJES_RECIBIDOS = 120   # tope duro de lo que se acepta en el POST
VENTANA_MENSAJES = 40          # lo que realmente se procesa (los ultimos)


def firmar(clave, chat_id, tipo, texto):
    """Firma de un mensaje emitido por el servidor."""
    if not clave or not chat_id:
        raise ValueError("Falta la clave o el id de conversacion para firmar.")
    mensaje = "\n".join(["chat-v1", str(chat_id), str(tipo), str(texto)])
    return hmac.new(
        str(clave).encode("utf-8"), mensaje.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def firma_valida(clave, chat_id, tipo, texto, firma):
    """True solo si el servidor emitio ese texto, con ese tipo, en esta conversacion."""
    if not isinstance(firma, str) or tipo not in TIPOS:
        return False
    esperada = firmar(clave, chat_id, tipo, texto)
    return hmac.compare_digest(esperada, firma)


def validar_historial(crudo, clave, chat_id):
    """
    Convierte lo que mando el navegador en un historial confiable.

    Devuelve (historial, descartados):
      historial    lista de {"rol", "texto", "tipo"}; empieza y termina
                   con un mensaje del usuario y tiene a lo sumo
                   VENTANA_MENSAJES elementos
      descartados  cuantos mensajes "bot" se botaron por no traer una
                   firma valida

    Lanza ErrorValidacion si la estructura es invalida, si algun mensaje
    del usuario excede el largo permitido o si no hay nada que responder.
    """
    if not isinstance(crudo, list) or not crudo:
        raise ErrorValidacion("Conversación vacía")
    if len(crudo) > MAX_MENSAJES_RECIBIDOS:
        raise ErrorValidacion("Conversación demasiado larga")

    limpios = []
    descartados = 0

    for m in crudo:
        if not isinstance(m, dict):
            raise ErrorValidacion("Mensaje con formato inválido")
        rol = m.get("rol")
        texto = m.get("texto")
        if rol not in (ROL_USUARIO, ROL_BOT) or not isinstance(texto, str):
            raise ErrorValidacion("Mensaje con formato inválido")

        if rol == ROL_USUARIO:
            texto = texto.strip()
            if not texto:
                continue
            if len(texto) > MAX_CARACTERES_USUARIO:
                raise ErrorValidacion("El mensaje es demasiado largo")
            limpios.append({"rol": ROL_USUARIO, "texto": texto, "tipo": TIPO_NORMAL})
            continue

        # Mensaje del asistente: solo vale si lo firmo este servidor.
        tipo = m.get("tipo", TIPO_NORMAL)
        if (not texto
                or len(texto) > MAX_CARACTERES_BOT
                or not firma_valida(clave, chat_id, tipo, texto, m.get("firma"))):
            descartados += 1
            continue
        limpios.append({"rol": ROL_BOT, "texto": texto, "tipo": tipo})

    # Ventana deslizante: una charla larga sigue funcionando con lo reciente.
    limpios = limpios[-VENTANA_MENSAJES:]
    while limpios and limpios[0]["rol"] != ROL_USUARIO:
        limpios.pop(0)

    if not limpios or limpios[-1]["rol"] != ROL_USUARIO:
        raise ErrorValidacion("No recibí tu mensaje. ¿Puedes escribirlo de nuevo?")

    return limpios, descartados

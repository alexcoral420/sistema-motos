"""
Autenticación por API key para la API externa (/api, la consume n8n).

La variable se sigue llamando API_WEBHOOK_KEY por compatibilidad con lo
ya configurado en Railway y en n8n, aunque el webhook ya no existe.

Dos llaves, para rotar sin corte:
  API_WEBHOOK_KEY            la principal. Si falta, la API responde 503
                             (fail-closed), aunque la anterior exista.
  API_WEBHOOK_KEY_ANTERIOR   opcional. Solo vive mientras dura una rotación.

Cómo rotar:
  1. Copiar el valor actual de API_WEBHOOK_KEY a API_WEBHOOK_KEY_ANTERIOR.
  2. Poner la llave nueva en API_WEBHOOK_KEY y desplegar. Desde aquí
     valen las dos.
  3. Cambiar la llave en n8n.
  4. Cuando el log (auditoria.api) deje de mostrar
     consumidor=n8n(anterior), borrar API_WEBHOOK_KEY_ANTERIOR.

La identidad del consumidor sale de QUÉ llave coincidió; la llave misma
(ni un fragmento) nunca se registra.
"""

import secrets
from functools import wraps
from flask import current_app, g, request, jsonify

# Identidades posibles de quien llama a /api. Van al log por petición.
CONSUMIDOR_N8N = "n8n"
CONSUMIDOR_N8N_ANTERIOR = "n8n(anterior)"
CONSUMIDOR_SIN_LLAVE = "sin_llave"
CONSUMIDOR_LLAVE_INVALIDA = "llave_invalida"
CONSUMIDOR_SIN_CONFIGURAR = "sin_configurar"
CONSUMIDOR_PUBLICO = "publico"      # rutas sin llave (avalúo, recordatorios)

_AUTORIZADOS = (CONSUMIDOR_N8N, CONSUMIDOR_N8N_ANTERIOR)


def _iguales(recibida: str, esperada: str) -> bool:
    """Comparación en tiempo constante. En bytes: compare_digest no
    acepta str con caracteres no ASCII (lanzaría un 500)."""
    return secrets.compare_digest(recibida.encode("utf-8"), esperada.encode("utf-8"))


def identificar_consumidor() -> str:
    """
    Quién hace la petición actual, según la cabecera Authorization.
    No decide la respuesta: solo clasifica.
    """
    principal = current_app.config.get("API_WEBHOOK_KEY")
    if not principal:
        return CONSUMIDOR_SIN_CONFIGURAR

    cabecera = request.headers.get("Authorization", "")
    if not cabecera.startswith("Bearer "):
        return CONSUMIDOR_SIN_LLAVE
    recibida = cabecera[7:]

    # Se comparan las dos siempre, sin atajo, para no delatar por tiempo
    # cuál de ellas coincidió.
    anterior = current_app.config.get("API_WEBHOOK_KEY_ANTERIOR")
    es_principal = _iguales(recibida, principal)
    es_anterior = bool(anterior) and _iguales(recibida, anterior)
    if es_principal:
        return CONSUMIDOR_N8N
    if es_anterior:
        return CONSUMIDOR_N8N_ANTERIOR
    return CONSUMIDOR_LLAVE_INVALIDA


def requiere_api_key(func):
    """Exige una API key válida en el header Authorization: Bearer <key>."""
    @wraps(func)
    def envoltura(*args, **kwargs):
        consumidor = identificar_consumidor()
        g.api_consumidor = consumidor

        if consumidor == CONSUMIDOR_SIN_CONFIGURAR:
            return jsonify({"error": "API no configurada"}), 503
        if consumidor == CONSUMIDOR_SIN_LLAVE:
            return jsonify({"error": "Falta autenticación"}), 401
        if consumidor not in _AUTORIZADOS:
            return jsonify({"error": "Autenticación inválida"}), 401

        return func(*args, **kwargs)

    # Marca para el log: si la petición se corta antes de llegar aquí
    # (un 429 del rate limit), el log igual sabe que la ruta pedía llave.
    envoltura.requiere_api_key = True
    return envoltura

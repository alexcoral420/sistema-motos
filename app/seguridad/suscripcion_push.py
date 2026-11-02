"""
Validación de la suscripción Web Push que manda el navegador
(PushSubscription.toJSON(): {endpoint, keys: {p256dh, auth}}).

Neutral (sin imports de app, supabase ni config; lo verifica un test): la
usan los recordatorios anónimos (app/servicios/recordatorios.py) y los
dispositivos del motero (app/servicios/alertas_motero.py), y el blueprint
del motero no puede arrastrar el repositorio del admin.

Por qué la lista de hosts: el servidor le hace POST al endpoint al enviar
un aviso. Sin la lista, cualquiera podría registrar una URL interna o
arbitraria y usar al servidor para atacarla (SSRF). Por eso también se
revalida al enviar, aunque la suscripción venga de la base.
"""

import base64
import re
from urllib.parse import urlsplit

from app.seguridad.validadores import ErrorValidacion

# Servicios de push de los navegadores. Se compara el host exacto o como
# subdominio (Mozilla y Windows reparten en varios subdominios).
HOSTS_PUSH = (
    "fcm.googleapis.com",           # Chrome, Edge (Android), Opera, Samsung
    "push.services.mozilla.com",    # Firefox
    "notify.windows.com",           # Edge (Windows)
    "push.apple.com",               # Safari (macOS, iOS 16.4+ instalada)
)
LARGO_MAX_ENDPOINT = 1000

# Largo de las claves de la suscripción, ya decodificadas de base64url:
# p256dh es un punto P-256 sin comprimir (65 bytes) y auth un secreto
# de 16 bytes (RFC 8291).
BYTES_P256DH = 65
BYTES_AUTH = 16

MENSAJE_SUSCRIPCION_INVALIDA = "La suscripción del navegador no es válida."


def _error() -> ErrorValidacion:
    return ErrorValidacion(MENSAJE_SUSCRIPCION_INVALIDA, "suscripcion")


def _host_permitido(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in HOSTS_PUSH)


def _clave_b64url(valor, largo: int) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", valor):
        raise _error()
    try:
        crudo = base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))
    except (ValueError, TypeError):
        raise _error()
    if len(crudo) != largo:
        raise _error()
    return valor


def validar_suscripcion(valor) -> dict:
    """
    Valida la suscripción y la devuelve reconstruida campo por campo, o
    lanza ErrorValidacion. Se reconstruye en vez de devolver lo recibido:
    así no entra a la base ningún campo extra que el cliente haya colado.
    """
    if not isinstance(valor, dict):
        raise _error()
    endpoint = valor.get("endpoint")
    claves = valor.get("keys")
    if not isinstance(endpoint, str) or len(endpoint) > LARGO_MAX_ENDPOINT or not isinstance(claves, dict):
        raise _error()
    partes = urlsplit(endpoint)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or partes.port not in (None, 443) or partes.username or not _host_permitido(host):
        raise _error()
    return {
        "endpoint": endpoint,
        "keys": {
            "p256dh": _clave_b64url(claves.get("p256dh"), BYTES_P256DH),
            "auth": _clave_b64url(claves.get("auth"), BYTES_AUTH),
        },
    }

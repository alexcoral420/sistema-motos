"""
Servicio de recordatorios: avisos push de vencimiento de SOAT y
revisión técnico-mecánica (Fase 1: modo anónimo, sin cuenta).

Entrada externa (POST /api/recordatorios, JSON desde el navegador):

    {
      "fecha_soat":  "2027-03-15" | null,
      "fecha_tecno": "2027-05-02" | null,
      "placa":       "ABC12D" | null,
      "acepta_politica": true,
      "suscripcion": {"endpoint": "https://...", "keys": {"p256dh": "...", "auth": "..."}}
    }

Qué se valida aquí y por qué:
  - Fechas: al menos una; formato ISO; en un rango razonable.
  - Placa: opcional; formato de placa de moto colombiana.
  - Consentimiento: obligatorio (placa + suscripción son datos personales,
    Ley 1581); se guarda la versión de la política vigente.
  - Suscripción: forma y longitudes, y que el endpoint sea https de un
    servicio de push conocido. En la Fase 2 el servidor le hará POST a esa
    URL: sin esta lista, cualquiera podría registrar una URL interna o
    arbitraria y usar al servidor para atacarla (SSRF).

El token que identifica al recordatorio se genera aquí, se devuelve en
claro UNA sola vez y en la base queda solo su SHA-256.
"""

import base64
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from pywebpush import WebPushException, webpush

from config import Config
from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios.contratos import HORA_COLOMBIA

# Rango aceptado para las fechas de vencimiento. Hacia atrás se tolera un
# poco (alguien con el SOAT recién vencido igual quiere el aviso del
# próximo); hacia adelante, SOAT y tecno se renuevan cada año o menos.
DIAS_ATRAS_MAX = 365
DIAS_ADELANTE_MAX = 2 * 365

# Placa de moto en Colombia: 3 letras + 2 números + 1 letra (ABC12D). Las
# más viejas no traen la letra final (ABC12).
PATRON_PLACA = re.compile(r"^[A-Z]{3}[0-9]{2}[A-Z]?$")

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

# Envío (Fase 2). Si el dispositivo está apagado, el servicio de push
# guarda el mensaje hasta TTL_PUSH segundos; pasado eso se descarta.
TTL_PUSH = 24 * 60 * 60
TIMEOUT_PUSH = 10
# Respuestas del servicio de push que significan "esta suscripción ya no
# existe" (el usuario revocó el permiso, desinstaló, limpió datos...).
ESTADOS_SUSCRIPCION_MUERTA = (404, 410)

# Envío automático (Fase 3): días antes del vencimiento en que se avisa.
UMBRALES_AVISO = (30, 15, 7, 1)
# Tipo de aviso → (columna con la fecha, nombre para el usuario).
TIPOS_AVISO = {
    "soat": ("fecha_soat", "SOAT"),
    "tecno": ("fecha_tecno", "tecnomecánica"),
}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")
URL_AVISO = "/"


def _hoy() -> date:
    return datetime.now(HORA_COLOMBIA).date()


def _fecha(valor, campo: str, nombre: str):
    if valor in (None, ""):
        return None
    if not isinstance(valor, str):
        raise ErrorValidacion(f"La fecha de {nombre} no es válida.", campo)
    try:
        fecha = date.fromisoformat(valor)
    except ValueError:
        raise ErrorValidacion(f"La fecha de {nombre} no es válida.", campo)
    hoy = _hoy()
    if not (hoy - timedelta(days=DIAS_ATRAS_MAX) <= fecha <= hoy + timedelta(days=DIAS_ADELANTE_MAX)):
        raise ErrorValidacion(
            f"La fecha de {nombre} debe estar entre hace un año y dentro de dos años.", campo)
    return fecha


def _placa(valor):
    if valor in (None, ""):
        return None
    if not isinstance(valor, str):
        raise ErrorValidacion("La placa no es válida.", "placa")
    placa = re.sub(r"[\s-]", "", valor).upper()
    if not placa:
        return None
    if not PATRON_PLACA.match(placa):
        raise ErrorValidacion("La placa debe tener el formato ABC12D.", "placa")
    return placa


def _host_permitido(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in HOSTS_PUSH)


def _clave_b64url(valor, nombre: str, largo: int):
    error = ErrorValidacion("La suscripción del navegador no es válida.", "suscripcion")
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", valor):
        raise error
    try:
        crudo = base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))
    except (ValueError, TypeError):
        raise error
    if len(crudo) != largo:
        raise error
    return valor


def _suscripcion(valor) -> dict:
    error = ErrorValidacion("La suscripción del navegador no es válida.", "suscripcion")
    if not isinstance(valor, dict):
        raise error
    endpoint = valor.get("endpoint")
    claves = valor.get("keys")
    if not isinstance(endpoint, str) or len(endpoint) > LARGO_MAX_ENDPOINT or not isinstance(claves, dict):
        raise error
    partes = urlsplit(endpoint)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or partes.port not in (None, 443) or partes.username or not _host_permitido(host):
        raise error
    # Se reconstruye en vez de guardar lo recibido: así no entra a la base
    # ningún campo extra que el cliente haya querido colar.
    return {
        "endpoint": endpoint,
        "keys": {
            "p256dh": _clave_b64url(claves.get("p256dh"), "p256dh", BYTES_P256DH),
            "auth": _clave_b64url(claves.get("auth"), "auth", BYTES_AUTH),
        },
    }


def validar_solicitud(datos) -> dict:
    """
    Valida el JSON recibido y devuelve los datos limpios. Lanza
    ErrorValidacion con un mensaje apto para el usuario.
    """
    if not isinstance(datos, dict):
        raise ErrorValidacion("La solicitud no es válida.")

    fecha_soat = _fecha(datos.get("fecha_soat"), "fecha_soat", "vencimiento del SOAT")
    fecha_tecno = _fecha(datos.get("fecha_tecno"), "fecha_tecno", "vencimiento de la tecnomecánica")
    if fecha_soat is None and fecha_tecno is None:
        raise ErrorValidacion("Ingresa al menos una fecha: SOAT o tecnomecánica.", "fecha_soat")

    if datos.get("acepta_politica") is not True:
        raise ErrorValidacion("Debes aceptar la política de privacidad.", "acepta_politica")

    return {
        "fecha_soat": fecha_soat,
        "fecha_tecno": fecha_tecno,
        "placa": _placa(datos.get("placa")),
        "suscripcion": _suscripcion(datos.get("suscripcion")),
    }


def hash_token(token: str) -> str:
    """SHA-256 del token: lo único que se guarda y por lo que se busca."""
    return hashlib.sha256(token.encode()).hexdigest()


def crear(datos) -> str:
    """
    Valida, guarda el recordatorio y devuelve el token en claro. Es la
    única vez que el token sale del servidor: la base guarda su hash.
    """
    limpio = validar_solicitud(datos)
    token = secrets.token_urlsafe(32)
    politica = repositorios.obtener_politica_vigente()
    repositorios.crear_recordatorio({
        "token_hash": hash_token(token),
        "suscripcion": limpio["suscripcion"],
        "fecha_soat": limpio["fecha_soat"].isoformat() if limpio["fecha_soat"] else None,
        "fecha_tecno": limpio["fecha_tecno"].isoformat() if limpio["fecha_tecno"] else None,
        "placa": limpio["placa"],
        "politica_id": politica["id"] if politica else None,
        "version_politica": politica["version"] if politica else None,
    })
    return token


def enviar_push(recordatorio: dict, titulo: str, cuerpo: str, url: str = "/") -> dict:
    """
    Envía una notificación push a la suscripción del recordatorio.

    Devuelve {"ok", "estado", "desactivados", "detalle"}. Si el servicio de
    push responde 404/410, la suscripción murió: se desactivan todos los
    recordatorios con ese endpoint. Otros errores no tocan la base (pueden
    ser pasajeros: 429, 5xx, red).
    """
    if not (Config.VAPID_PRIVATE_KEY and Config.VAPID_SUBJECT):
        raise RuntimeError("Faltan VAPID_PRIVATE_KEY / VAPID_SUBJECT en el entorno.")

    # Se revalida aunque venga de la base: una fila escrita por fuera del
    # servicio no debe poder hacer que el servidor le pegue a cualquier URL.
    suscripcion = _suscripcion(recordatorio.get("suscripcion"))
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
                "desactivados": 0, "detalle": "enviado"}
    except WebPushException as e:
        estado = e.status_code
        desactivados = 0
        if estado in ESTADOS_SUSCRIPCION_MUERTA:
            desactivados = repositorios.desactivar_recordatorios_por_endpoint(
                suscripcion["endpoint"], datetime.now(HORA_COLOMBIA).isoformat())
        return {"ok": False, "estado": estado, "desactivados": desactivados, "detalle": str(e)}


def _como_fecha(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(valor)


def avisos_a_enviar(recordatorios, hoy: date, ya_enviados, umbrales=UMBRALES_AVISO) -> list:
    """
    Decide qué avisos salen hoy. Función pura, sin I/O.

    Para cada recordatorio activo y cada tipo (SOAT y tecno, por separado)
    con dias = fecha - hoy: si dias < 0 ya venció y no se avisa; si no, el
    umbral que corresponde es el más chico de los umbrales que sea >= dias
    ("bucket"). Se envía solo si (id, tipo, umbral) no está en ya_enviados.

    El bucket hace de catch-up: si el job no corrió justo el día 30, el
    aviso de 30 sale el día 29; y una vez enviado no se repite.

    Devuelve [(recordatorio_id, tipo, umbral, dias_restantes), ...].
    """
    ordenados = sorted(umbrales)
    avisos = []
    for r in recordatorios:
        if not r.get("activo", True):
            continue
        for tipo, (columna, _) in TIPOS_AVISO.items():
            fecha = _como_fecha(r.get(columna))
            if fecha is None:
                continue
            dias = (fecha - hoy).days
            if dias < 0:
                continue
            umbral = next((u for u in ordenados if u >= dias), None)
            if umbral is None or (r["id"], tipo, umbral) in ya_enviados:
                continue
            avisos.append((r["id"], tipo, umbral, dias))
    return avisos


def texto_aviso(tipo: str, fecha, dias: int) -> dict:
    """Título y cuerpo de la notificación de vencimiento."""
    fecha = _como_fecha(fecha)
    nombre = TIPOS_AVISO[tipo][1]
    fecha_txt = f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"
    if dias == 0:
        cuando = "Vence hoy"
    elif dias == 1:
        cuando = "Vence mañana"
    else:
        cuando = f"Vence en {dias} días"
    return {
        "titulo": f"Tu {nombre} vence pronto",
        "cuerpo": f"{cuando} ({fecha_txt}). Renuévalo para evitar multas.",
    }

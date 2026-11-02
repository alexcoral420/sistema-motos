"""
Cuentas del motero ("Mi espacio"): validación de formularios y decisiones
puras alrededor de la sesión. Sin red ni base: se prueba sin Supabase.

Importante: este módulo lo usa el blueprint del motero, que tiene prohibido
el cliente service_role. Por eso NO importa app.db.repositorios ni nada que
lo arrastre (lo verifica tests/test_cuentas_motero.py).

Qué se pide al registrarse:
  - email y contraseña (la cuenta la guarda Supabase Auth, no nosotros).
  - nombre (obligatorio) y teléfono (opcional, solo forma).
  - consentimiento obligatorio: la versión de la política que se acepta la
    estampa el trigger handle_new_user() (migración 021), no este código.
"""

import re

from app.seguridad.tiempo import hoy_colombia
from app.seguridad.validadores import (
    ErrorValidacion, validar_entero, validar_placa_moto, validar_telefono, validar_texto,
)

# Contraseña: 8 como mínimo razonable; 72 es el tope de bcrypt (Supabase
# ignora lo que pase de ahí, así que mejor rechazarlo que truncarlo callado).
PASSWORD_MIN = 8
PASSWORD_MAX = 72

# Forma básica de email: algo@algo.tld, sin espacios. Que exista lo decide
# Supabase (o el correo de confirmación), no una regex.
PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX = 254

# Si al token le queda menos que esto, se refresca antes de usarlo, para
# que no expire a mitad de la petición.
MARGEN_REFRESCO_SEG = 60

# Errores de Supabase Auth (campo `code` de AuthApiError) -> mensaje para el
# motero. Lo que no está aquí cae en el mensaje genérico.
MENSAJES_ERROR_AUTH = {
    "invalid_credentials": "Correo o contraseña incorrectos.",
    "email_not_confirmed": "Todavía no confirmas tu correo. Revisa tu bandeja de entrada.",
    "user_already_exists": "Ya hay una cuenta con ese correo. Ingresa con tu contraseña.",
    "email_exists": "Ya hay una cuenta con ese correo. Ingresa con tu contraseña.",
    "weak_password": "La contraseña es muy débil. Usa una más larga o combina letras y números.",
    "over_email_send_rate_limit": "Hicimos demasiados envíos de correo. Intenta de nuevo en unos minutos.",
    "over_request_rate_limit": "Demasiados intentos. Espera un momento y vuelve a intentarlo.",
    "signup_disabled": "El registro no está disponible en este momento.",
}
MENSAJE_ERROR_GENERICO = "No pudimos completar la operación. Intenta de nuevo en un momento."


def _email(valor) -> str:
    email = validar_texto(valor, "correo", max_len=EMAIL_MAX)
    email = email.lower()
    if not PATRON_EMAIL.match(email):
        raise ErrorValidacion("El correo no es válido.", "correo")
    return email


def _password(valor) -> str:
    # Sin strip: los espacios cuentan como parte de la contraseña.
    if not isinstance(valor, str) or valor == "":
        raise ErrorValidacion("La contraseña es obligatoria.", "password")
    if len(valor) < PASSWORD_MIN:
        raise ErrorValidacion(
            f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres.", "password")
    if len(valor.encode()) > PASSWORD_MAX:
        raise ErrorValidacion("La contraseña es demasiado larga.", "password")
    return valor


def validar_registro(form) -> dict:
    """
    Valida el formulario de /registro. Devuelve los datos limpios o lanza
    ErrorValidacion. `form` es cualquier mapeo (request.form, dict).
    """
    datos = {
        "email": _email(form.get("email")),
        "password": _password(form.get("password")),
        "nombre": validar_texto(form.get("nombre"), "nombre", min_len=2, max_len=120),
    }

    telefono = (form.get("telefono") or "").strip()
    if telefono:
        telefono = re.sub(r"[\s-]", "", telefono)
        datos["telefono"] = validar_telefono(telefono, "telefono")
    else:
        datos["telefono"] = None

    # Casilla HTML: llega "on" si está marcada; si no, no llega.
    if form.get("acepta_politica") not in ("on", "true", "1"):
        raise ErrorValidacion("Debes aceptar la política de privacidad.", "acepta_politica")

    return datos


def validar_ingreso(form) -> dict:
    """Valida el formulario de /ingresar (sin reglas de largo: eso es del registro)."""
    email = _email(form.get("email"))
    password = form.get("password")
    if not isinstance(password, str) or password == "":
        raise ErrorValidacion("La contraseña es obligatoria.", "password")
    return {"email": email, "password": password}


def metadata_registro(datos: dict) -> dict:
    """
    Lo que viaja en options.data de sign_up y lee el trigger handle_new_user().
    El consentimiento va como "true" solo porque validar_registro ya lo exigió.
    """
    return {
        "nombre": datos["nombre"],
        "telefono": datos["telefono"],
        "acepta_politica": "true",
    }


def mensaje_error_auth(codigo) -> str:
    """Traduce el código de error de Supabase Auth a un mensaje para el motero."""
    return MENSAJES_ERROR_AUTH.get(codigo or "", MENSAJE_ERROR_GENERICO)


def necesita_refresco(expira_en, ahora: float) -> bool:
    """
    True si el access token ya venció o vence dentro del margen.
    `expira_en` es el epoch (segundos) que devuelve Supabase en la sesión;
    si falta o no es número, se asume vencido.
    """
    try:
        return float(expira_en) - ahora < MARGEN_REFRESCO_SEG
    except (TypeError, ValueError):
        return True


def destino_seguro(siguiente, por_defecto: str) -> str:
    """
    Destino después de ingresar (?next=...). Solo rutas internas: empieza
    por "/" pero no por "//" ni "/\\" (que el navegador toma como otro
    dominio). Cualquier otra cosa -> por_defecto. Evita el open redirect.
    """
    if (not isinstance(siguiente, str) or not siguiente.startswith("/")
            or siguiente.startswith("//") or "\\" in siguiente
            or any(c in siguiente for c in "\r\n\t")):
        return por_defecto
    return siguiente


# ---------- Motos del motero (Capa 1) ----------

# Año de la moto: desde 1950 hasta el año próximo (los modelos del año
# siguiente salen a la venta antes de que empiece). La base tiene un CHECK
# más amplio (1950-2100) solo como red de seguridad.
ANIO_MIN = 1950

# Tope de motos por cuenta: nadie normal tiene más; evita que una cuenta
# se use para llenar la tabla.
MAX_MOTOS_POR_MOTERO = 20

MARCA_MODELO_MAX = 60

# Errores de PostgREST (campo `code` de APIError) al escribir una moto.
MENSAJES_ERROR_MOTO = {
    "23505": "Ya tienes una moto con esa placa.",
    "23514": "Alguno de los datos está fuera del rango permitido.",
    "42501": "No tienes permiso para hacer eso.",
    "PGRST301": "Tu sesión venció. Ingresa de nuevo.",
}
MENSAJE_MOTO_NO_ENCONTRADA = "Esa moto no existe o no es tuya."
MENSAJE_TOPE_MOTOS = f"Puedes registrar hasta {MAX_MOTOS_POR_MOTERO} motos."


def _anio_actual() -> int:
    return hoy_colombia().year


def anio_maximo() -> int:
    """Año más reciente aceptado para una moto: el próximo."""
    return _anio_actual() + 1


def validar_moto(form) -> dict:
    """
    Valida el formulario de agregar/editar moto. Devuelve los datos limpios
    (sin usuario_id: ese lo pone la ruta desde la sesión) o lanza
    ErrorValidacion.
    """
    return {
        "marca": validar_texto(form.get("marca"), "marca", min_len=2, max_len=MARCA_MODELO_MAX),
        "modelo": validar_texto(form.get("modelo"), "modelo", min_len=1, max_len=MARCA_MODELO_MAX),
        "anio": validar_entero(form.get("anio"), "año", minimo=ANIO_MIN, maximo=anio_maximo()),
        "placa": validar_placa_moto(form.get("placa"), "placa"),
    }


def mensaje_error_moto(codigo) -> str:
    """Traduce el código de error de PostgREST a un mensaje para el motero."""
    return MENSAJES_ERROR_MOTO.get(str(codigo or ""), MENSAJE_ERROR_GENERICO)

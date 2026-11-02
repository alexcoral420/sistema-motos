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

from app.seguridad.validadores import ErrorValidacion, validar_telefono, validar_texto

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

"""
Configuración del proyecto por ambiente.

En lugar de tener valores sueltos mezclados en el código (como en el
app.py viejo), centralizamos TODA la configuración aquí, en clases.
La app elegirá una clase u otra según la variable FLASK_ENV del .env.

Por qué en clases y no en variables sueltas:
- Producción NO puede arrancar con debug encendido, por diseño.
- La seguridad deja de depender de "acordarse" y pasa a estar
  garantizada por la estructura.
"""

import os
from dotenv import load_dotenv

# Lee el archivo .env y carga sus valores como variables de entorno.
# A partir de aquí, os.environ.get("LO_QUE_SEA") ve lo que pusiste en .env.
load_dotenv()


class Config:
    """
    Configuración BASE: lo común a todos los ambientes.
    Desarrollo y Producción heredan de aquí y solo cambian lo distinto.
    """

    # Clave que Flask usa para firmar las cookies de sesión (login).
    # Si alguien la conociera, podría falsificar sesiones. Por eso vive
    # en el .env y NUNCA se escribe directo en el código.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # --- Credenciales externas (todas leídas del .env) ---
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")

    # --- Admin del panel ---
    ADMIN_USUARIO = os.environ.get("ADMIN_USUARIO")
    # Guardamos el HASH, nunca la contraseña en texto plano.
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")

    # --- Meta / WhatsApp Cloud API ---
    VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
    PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")

    # --- Seguridad de cookies de sesión (valores base, seguros) ---
    # Impide que JavaScript del navegador lea la cookie de sesión
    # (defensa contra robo de sesión por XSS).
    SESSION_COOKIE_HTTPONLY = True
    # La cookie no se envía en peticiones que vienen de otro sitio
    # (defensa contra CSRF).
    SESSION_COOKIE_SAMESITE = "Lax"


class DesarrolloConfig(Config):
    """
    Para tu máquina local. Aquí SÍ queremos ver los errores completos.
    """
    DEBUG = True
    # En local trabajas sobre http (no https), así que la cookie no
    # puede exigir conexión segura o el login no funcionaría.
    SESSION_COOKIE_SECURE = False


class ProduccionConfig(Config):
    """
    Para Railway. Máxima seguridad, sin excepciones.
    """
    # debug SIEMPRE apagado: jamás mostramos tracebacks a un visitante.
    # Esto cierra la vulnerabilidad #5 de tu diagnóstico, por diseño.
    DEBUG = False
    # La cookie de sesión SOLO viaja por https. En producción tienes
    # dominio con certificado, así que esto protege la sesión en tránsito.
    SESSION_COOKIE_SECURE = True


# Diccionario que traduce el texto de FLASK_ENV a la clase correcta.
# El factory (que haremos después) lo usará para elegir la config.
config_por_nombre = {
    "development": DesarrolloConfig,
    "production": ProduccionConfig,
}
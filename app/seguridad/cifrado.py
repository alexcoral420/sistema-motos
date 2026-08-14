# app/seguridad/cifrado.py
# Modulo de cifrado para datos personales sensibles.
#
# Usa cifrado simetrico (Fernet, de la libreria cryptography):
#   - Una sola CLAVE secreta cifra y descifra.
#   - La clave vive en el .env (CLAVE_CIFRADO), NUNCA en la base ni en git.
#   - Si roban la base, ven solo texto cifrado (gAAAA...), inutil sin la clave.
#
# Concepto: la clave y los datos viven SEPARADOS. Esa separacion es la seguridad.

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
import hashlib

def _obtener_fernet():
    """
    Crea el objeto Fernet con la clave del .env.
    Se crea en cada llamada (es barato) para tomar siempre la clave actual.
    """
    clave = current_app.config.get("CLAVE_CIFRADO")
    if not clave:
        raise RuntimeError(
            "Falta CLAVE_CIFRADO en la configuracion. "
            "Genera una con Fernet.generate_key() y ponla en el .env."
        )
    # Fernet espera bytes; si la clave vino como str, la codificamos.
    if isinstance(clave, str):
        clave = clave.encode()
    return Fernet(clave)


def cifrar(texto):
    """
    Cifra un texto y devuelve el resultado cifrado (str, listo para guardar).
    Si el texto viene vacio o None, devuelve None (no ciframos vacios).
    """
    if texto is None or texto == "":
        return None
    f = _obtener_fernet()
    # Fernet cifra bytes; convertimos el texto a bytes y el resultado a str.
    cifrado_bytes = f.encrypt(str(texto).encode())
    return cifrado_bytes.decode()


def descifrar(texto_cifrado):
    """
    Descifra un texto cifrado y devuelve el original (str).
    Si viene vacio, devuelve None. Si el dato esta corrupto o la clave
    no corresponde, devuelve None en vez de reventar (fail-safe).
    """
    if texto_cifrado is None or texto_cifrado == "":
        return None
    f = _obtener_fernet()
    try:
        original_bytes = f.decrypt(str(texto_cifrado).encode())
        return original_bytes.decode()
    except InvalidToken:
        # El dato no se pudo descifrar (clave incorrecta o dato corrupto).
        # No revelamos detalles; devolvemos None.
        return None

def calcular_hash(texto):
    """
    Devuelve la huella SHA-256 de un texto.

    A diferencia del cifrado (que es reversible con la clave), el hash
    es de una sola via: no se puede volver al texto original. Sirve para
    PROBAR INTEGRIDAD: si el texto cambia aunque sea una coma, el hash
    cambia por completo. Lo usamos para archivar la politica de privacidad
    y poder demostrar que la version que acepto el cliente no fue alterada.
    """
    if not texto:
        return None
    return hashlib.sha256(texto.encode()).hexdigest()
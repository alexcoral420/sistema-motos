"""
Seguridad de contraseñas: hashing y verificación.

En el app.py viejo se comparaba la contraseña en texto plano:
    if password == ADMIN_PASSWORD   # <-- vulnerabilidad #1

Aquí lo hacemos bien, con werkzeug (incluido en Flask):
  - hashear_password(): convierte una contraseña en un hash irreversible.
    Se usa UNA vez, para generar el valor que guardas en el .env.
  - verificar_password(): compara lo que alguien escribió contra el hash
    guardado, sin conocer nunca la contraseña real.

Un hash es una "huella digital" de una sola vía: de la contraseña sale
el hash, pero del hash NO se puede volver a la contraseña.
"""

from werkzeug.security import generate_password_hash, check_password_hash


def hashear_password(password_plano: str) -> str:
    """
    Convierte una contraseña en texto plano en un hash seguro.

    Se usa una sola vez (desde la terminal) para generar el valor que
    irá en ADMIN_PASSWORD_HASH del .env. No se usa en el login normal.

    pbkdf2:sha256 es el algoritmo; werkzeug le añade una "sal" aleatoria
    (un valor único por hash) para que dos contraseñas iguales produzcan
    hashes distintos. Eso frena los ataques por tablas precalculadas.
    """
    return generate_password_hash(password_plano)


def verificar_password(hash_guardado: str, password_intento: str) -> bool:
    """
    Comprueba si la contraseña intentada coincide con el hash guardado.

    Devuelve True si coincide, False si no. Nunca "descifra" el hash:
    calcula el hash del intento y compara. Así el login funciona sin
    almacenar jamás la contraseña real.
    """
    if not hash_guardado:
        # Si por error el hash está vacío, negamos el acceso por seguridad.
        return False
    return check_password_hash(hash_guardado, password_intento)
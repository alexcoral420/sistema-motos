
def autenticar(usuario: str, password: str):
    from app.db import repositorios   # import local: rompe el ciclo
    datos = repositorios.obtener_usuario_por_nombre(usuario)
from werkzeug.security import generate_password_hash, check_password_hash
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




def autenticar(usuario: str, password: str):
    """
    Verifica usuario y contraseña contra la tabla de usuarios.

    Devuelve el dict del usuario si las credenciales son correctas,
    o None si no. Nunca revela si falló el usuario o la contraseña:
    un atacante no debe saber si un usuario existe (no dar pistas).
    """
    from app.db import repositorios   # import local: evita el ciclo de imports

    datos = repositorios.obtener_usuario_por_nombre(usuario)
    if not datos:
        return None

    if verificar_password(datos["password_hash"], password):
        return datos
    return None
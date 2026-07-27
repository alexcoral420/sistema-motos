"""
Servicio de gestión de usuarios: crear y desactivar.

Aquí viven las SALVAGUARDAS de seguridad. El repositorio solo mueve
datos; este servicio decide si una operación es permitida. Es la capa
crítica de la gestión de usuarios: cada regla previene un desastre
concreto (perder acceso, escalar privilegios, quedar sin admin).

Toda operación recibe 'actor' = el usuario que la ejecuta (de la sesión),
para validar qué tiene permitido hacer.
"""

from werkzeug.security import generate_password_hash

from app.db import repositorios
from app.seguridad.logging_config import obtener_logger

ROLES_VALIDOS = {"admin", "asesor", "gerencia"}


class ErrorGestionUsuario(Exception):
    """Error de negocio al crear/desactivar (mensaje mostrable al usuario)."""
    pass


def listar():
    """Todos los usuarios para el panel (sin password_hash)."""
    return repositorios.listar_usuarios()


def crear(actor_rol: str, usuario: str, nombre: str, password: str,
          rol: str, sede_id):
    """
    Crea un usuario aplicando las salvaguardas.

    actor_rol: el rol de QUIEN crea (admin o gerencia).
    Lanza ErrorGestionUsuario con un mensaje claro si algo no cumple.
    """
    usuario = (usuario or "").strip()
    nombre = (nombre or "").strip()

    # --- Validaciones de forma ---
    if not usuario or not nombre:
        raise ErrorGestionUsuario("El usuario y el nombre son obligatorios.")
    if len(password or "") < 8:
        raise ErrorGestionUsuario("La contraseña debe tener al menos 8 caracteres.")
    if rol not in ROLES_VALIDOS:
        raise ErrorGestionUsuario("Rol no válido.")

    # --- SALVAGUARDA: gerencia solo crea asesores ---
    # Nadie puede crear a alguien con más poder que él mismo.
    if actor_rol == "gerencia" and rol != "asesor":
        raise ErrorGestionUsuario(
            "Gerencia solo puede crear usuarios con rol asesor.")

    # --- Crear (la contraseña se hashea AQUÍ, nunca se guarda en texto) ---
    try:
        repositorios.crear_usuario({
            "usuario": usuario,
            "password_hash": generate_password_hash(password),
            "nombre_completo": nombre,
            "rol": rol,
            "sede_id": sede_id,
            "activo": True,
        })
    except Exception as e:
        # El caso más común: usuario duplicado (unique en la tabla).
        raise ErrorGestionUsuario(
            "No se pudo crear el usuario. ¿Ya existe ese nombre de usuario?")

    obtener_logger().info(
        "Usuario creado: '%s' (rol %s) por un %s.", usuario, rol, actor_rol)


def desactivar(actor_id: int, actor_rol: str, objetivo_id: int):
    """
    Desactiva un usuario (borrado lógico) aplicando las salvaguardas.

    actor_id/actor_rol: quién ejecuta. objetivo_id: a quién desactivar.
    """
    objetivo = repositorios.obtener_usuario_por_id(objetivo_id)
    if not objetivo:
        raise ErrorGestionUsuario("El usuario no existe.")

    # --- SALVAGUARDA: nadie se desactiva a sí mismo ---
    # Evita quedar fuera del sistema por accidente.
    if objetivo_id == actor_id:
        raise ErrorGestionUsuario("No puedes desactivarte a ti mismo.")

    # --- SALVAGUARDA: gerencia solo desactiva asesores ---
    if actor_rol == "gerencia" and objetivo["rol"] != "asesor":
        raise ErrorGestionUsuario(
            "Gerencia solo puede desactivar usuarios con rol asesor.")

    # --- SALVAGUARDA: no desactivar al último admin activo ---
    # Sin admins activos, nadie podría administrar el sistema.
    if objetivo["rol"] == "admin" and repositorios.contar_admins_activos() <= 1:
        raise ErrorGestionUsuario(
            "No puedes desactivar al último administrador activo.")

    # Si ya estaba inactivo, no hacemos nada (idempotente).
    if not objetivo["activo"]:
        raise ErrorGestionUsuario("Ese usuario ya está desactivado.")

    repositorios.desactivar_usuario(objetivo_id)

    obtener_logger().warning(
        "Usuario desactivado: '%s' (id %s) por un %s (id %s).",
        objetivo["usuario"], objetivo_id, actor_rol, actor_id)
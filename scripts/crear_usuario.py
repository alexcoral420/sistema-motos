"""
Crea un usuario en la tabla 'usuarios' con la contraseña correctamente
hasheada (scrypt, igual que el login del sistema).

Uso interactivo:
    python scripts/crear_usuario.py
"""

import sys
import os
import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash
from app.db.cliente import get_supabase_admin


def main():
    print("=== Crear usuario ===\n")

    usuario = input("Usuario (para login, ej: carlos.perez): ").strip()
    nombre = input("Nombre completo: ").strip()

    print("\nRol:")
    print("  1) admin  (super usuario: puede todo)")
    print("  2) asesor (solo agregar y marcar vendida)")
    opcion = input("Elige 1 o 2: ").strip()
    rol = "admin" if opcion == "1" else "asesor"

    sede_id = input("ID de sede (1 = Principal, 2 = Boyaca): ").strip()
    sede_id = int(sede_id) if sede_id else None

    password = getpass.getpass("Contrasena: ")
    password2 = getpass.getpass("Repite la contrasena: ")

    if password != password2:
        print("\n[X] Las contrasenas no coinciden. Cancelado.")
        return
    if len(password) < 8:
        print("\n[X] La contrasena debe tener al menos 8 caracteres. Cancelado.")
        return

    password_hash = generate_password_hash(password)

    supabase = get_supabase_admin()
    try:
        resultado = supabase.table("usuarios").insert({
            "usuario": usuario,
            "password_hash": password_hash,
            "nombre_completo": nombre,
            "rol": rol,
            "sede_id": sede_id,
            "activo": True,
        }).execute()
        print(f"\n[OK] Usuario '{usuario}' creado como {rol}.")
    except Exception as e:
        print(f"\n[X] No se pudo crear: {e}")


if __name__ == "__main__":
    main()

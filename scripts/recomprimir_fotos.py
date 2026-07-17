"""
Recomprime las fotos que se subieron ANTES de la compresión automática.

Uso:
    python scripts/recomprimir_fotos.py           <- SIMULACIÓN (no toca nada)
    python scripts/recomprimir_fotos.py --aplicar <- ejecuta de verdad

Qué hace por cada foto vieja:
  1. La descarga del bucket.
  2. La recomprime (mismo proceso que las nuevas).
  3. Sube la versión WebP con un nombre nuevo.
  4. Actualiza la URL en la base.
  5. Borra el archivo viejo del bucket.

Es una herramienta de mantenimiento, no parte de la app. Vive en
scripts/ porque se ejecuta a mano, una vez.
"""

import sys
import os

# Permite importar la app estando en scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.cliente import get_supabase_admin, get_supabase_publico
from app.servicios.archivos import _comprimir, generar_nombre_seguro

APLICAR = "--aplicar" in sys.argv


def procesar(path_viejo: str, carpeta: str = ""):
    """
    Recomprime un archivo del bucket. Devuelve (url_nueva, path_nuevo)
    o None si se salta.
    """
    # Ya es webp -> se subió con compresión, no hay nada que hacer.
    # Esto hace el script IDEMPOTENTE: correrlo dos veces no duplica trabajo.
    if not path_viejo or path_viejo.lower().endswith(".webp"):
        return None

    supabase = get_supabase_admin()

    # 1. Descargar el original.
    original = supabase.storage.from_("motos").download(path_viejo)
    peso_antes = len(original)

    # 2. Recomprimir.
    comprimido = _comprimir(original)
    peso_despues = len(comprimido)

    reduccion = 100 - (peso_despues * 100 // peso_antes)
    print(f"    {path_viejo}")
    print(f"      {peso_antes//1024} KB -> {peso_despues//1024} KB  ({reduccion}% menos)")

    if not APLICAR:
        return None  # Simulación: no tocamos nada.

    # 3. Subir la versión nueva.
    path_nuevo = generar_nombre_seguro("webp", carpeta)
    supabase.storage.from_("motos").upload(
        path=path_nuevo,
        file=comprimido,
        file_options={"content-type": "image/webp"},
    )
    url_nueva = supabase.storage.from_("motos").get_public_url(path_nuevo)

    # 4. Borrar el viejo (solo después de que el nuevo existe).
    supabase.storage.from_("motos").remove([path_viejo])

    return url_nueva, path_nuevo


def main():
    if APLICAR:
        print("=== MODO REAL: se van a modificar los datos ===")
    else:
        print("=== SIMULACIÓN: no se modifica nada ===")
        print("    (agrega --aplicar para ejecutar de verdad)")
    print()

    admin = get_supabase_admin()
    publico = get_supabase_publico()

    # --- Portadas ---
    print("PORTADAS:")
    motos = publico.table("motos").select("id, foto_path").execute().data
    for moto in motos:
        if not moto.get("foto_path"):
            continue
        resultado = procesar(moto["foto_path"])
        if resultado and APLICAR:
            url, path = resultado
            admin.table("motos").update(
                {"foto_url": url, "foto_path": path}).eq("id", moto["id"]).execute()

    # --- Galería ---
    print("\nGALERÍA:")
    fotos = publico.table("fotos_motos").select("id, foto_path").execute().data
    for foto in fotos:
        if not foto.get("foto_path"):
            continue
        resultado = procesar(foto["foto_path"], carpeta="galeria")
        if resultado and APLICAR:
            url, path = resultado
            admin.table("fotos_motos").update(
                {"foto_url": url, "foto_path": path}).eq("id", foto["id"]).execute()

    print("\nListo.")


if __name__ == "__main__":
    main()
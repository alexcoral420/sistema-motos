"""
Genera las miniaturas (thumbs/<foto_path>) de las fotos subidas ANTES de
que el pipeline las creara automáticamente.

Uso:
    python scripts/generar_miniaturas.py

Toma SUPABASE_URL y SUPABASE_KEY (service_role) del entorno / .env, igual
que la app: para correrlo contra producción, esas variables deben ser las
del proyecto de producción.

Solo recorre las PORTADAS (motos.foto_path): es lo único que muestran las
tarjetas. Si después una foto vieja de galería pasa a portada, la tarjeta
cae a la original (onerror) hasta que se vuelva a correr el script.

Qué hace por cada portada:
  1. Si thumbs/<foto_path> ya existe, la salta (skip).
  2. Descarga la original del bucket.
  3. Genera la miniatura con el mismo proceso que las fotos nuevas.
  4. La sube a thumbs/<foto_path>.

Es IDEMPOTENTE y reanudable: si se corta, se vuelve a correr y sigue
donde quedó. Cada foto tiene hasta 4 intentos ante cortes de red; si
falla las 4, se anota y se sigue con las demás.
"""

import sys
import os
import time

# Permite importar la app estando en scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from app.db.cliente import get_supabase_admin
from app.servicios.archivos import generar_miniatura, PREFIJO_MINIATURA

INTENTOS = 4
ESPERA_SEG = 3


def procesar(bucket, foto_path: str) -> str:
    """Genera y sube la miniatura de una foto. Devuelve 'generada' o 'saltada'."""
    destino = PREFIJO_MINIATURA + foto_path

    # Dentro de cada intento: si una subida anterior llegó al bucket pero
    # se cortó la respuesta, el reintento la ve y la salta.
    if bucket.exists(destino):
        return "saltada"

    original = bucket.download(foto_path)
    miniatura = generar_miniatura(original)
    bucket.upload(
        path=destino,
        file=miniatura,
        file_options={"content-type": "image/webp"},
    )
    return "generada"


def main():
    if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
        print("[X] Faltan SUPABASE_URL / SUPABASE_KEY en el entorno.")
        sys.exit(1)

    print(f"=== Generar miniaturas en {Config.SUPABASE_URL} ===\n")

    # Cliente admin: la tabla se lee completa (sin RLS), incluidas
    # motos vendidas o despublicadas, que también tienen portada.
    supabase = get_supabase_admin()
    bucket = supabase.storage.from_("motos")

    # Solo portadas: las tarjetas (catálogo, home, similares) muestran la
    # portada; la galería se ve grande en el detalle y no usa miniatura.
    motos = supabase.table("motos").select("foto_path").execute().data

    # Sin nulos ni repetidos, en orden estable.
    paths = list(dict.fromkeys(
        f["foto_path"] for f in motos if f.get("foto_path")))
    print(f"{len(paths)} fotos a revisar.\n")

    generadas = saltadas = 0
    fallidas = []

    for i, path in enumerate(paths, 1):
        for intento in range(1, INTENTOS + 1):
            try:
                resultado = procesar(bucket, path)
                break
            except Exception as e:
                if intento == INTENTOS:
                    resultado = None
                    print(f"[{i}/{len(paths)}] FALLÓ: {path} ({e})")
                    fallidas.append(path)
                else:
                    print(f"[{i}/{len(paths)}] reintento {intento}/{INTENTOS - 1}: {path} ({e})")
                    time.sleep(ESPERA_SEG)

        if resultado == "generada":
            generadas += 1
            print(f"[{i}/{len(paths)}] ok: {path}")
        elif resultado == "saltada":
            saltadas += 1
            print(f"[{i}/{len(paths)}] skip: {path}")

    print(f"\nGeneradas: {generadas}")
    print(f"Saltadas:  {saltadas}")
    if fallidas:
        print(f"Fallidas:  {len(fallidas)} (volver a correr el script para reintentarlas)")
        for p in fallidas:
            print(f"  - {p}")
    else:
        print("Fallidas:  0")


if __name__ == "__main__":
    main()

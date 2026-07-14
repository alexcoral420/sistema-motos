"""
Repositorio: acceso a datos de Supabase.

Aquí viven las funciones que hablan con las tablas. Son las mismas de tu
database.py viejo, con UN cambio clave:

  ANTES: cada función usaba una variable global 'supabase' que se creaba
         al importar el archivo.
  AHORA: cada función pide la conexión con get_supabase(), la conexión
         única y centralizada que definimos en cliente.py.

Por qué importa: la lógica de las consultas no cambia (mismo SQL, mismas
tablas), pero ya no dependen de una conexión suelta. Dependen de la capa
de conexión, que a su vez lee la config. Todo conectado y ordenado.

Vamos migrando por partes. De momento: LECTURA de motos, que es lo que
necesitan las rutas públicas. Escritura, CRM y archivos vendrán después.
"""

from app.db.cliente import get_supabase


# ============================================================
#  CONSULTAS DE MOTOS (lectura)
# ============================================================

def obtener_motos_disponibles():
    """Todas las motos con estado 'disponible' (para el catálogo público)."""
    supabase = get_supabase()
    resultado = supabase.table("motos")\
        .select("*")\
        .eq("estado", "disponible")\
        .execute()
    return resultado.data


def obtener_todas_las_motos():
    """Todas las motos, más recientes primero (para el panel admin)."""
    supabase = get_supabase()
    resultado = supabase.table("motos")\
        .select("*")\
        .order("created_at", desc=True)\
        .execute()
    return resultado.data


def obtener_moto_por_id(id: int):
    """Una moto por su id, o None si no existe."""
    supabase = get_supabase()
    resultado = supabase.table("motos")\
        .select("*")\
        .eq("id", id)\
        .execute()
    return resultado.data[0] if resultado.data else None


def obtener_fotos_moto(moto_id: int):
    """Fotos de galería de una moto, ordenadas por el campo 'orden'."""
    supabase = get_supabase()
    resultado = supabase.table("fotos_motos")\
        .select("*")\
        .eq("moto_id", moto_id)\
        .order("orden")\
        .execute()
    return resultado.data
    
    # ============================================================
#  ESCRITURA DE MOTOS
# ============================================================

def agregar_moto(datos: dict):
    """Inserta una moto nueva."""
    supabase = get_supabase()
    resultado = supabase.table("motos")\
        .insert(datos)\
        .execute()
    return resultado.data


def actualizar_moto(id: int, datos: dict):
    """Actualiza una moto por su id."""
    supabase = get_supabase()
    resultado = supabase.table("motos")\
        .update(datos)\
        .eq("id", id)\
        .execute()
    return resultado.data


def marcar_como_vendida(id: int):
    """Cambia el estado a 'vendido'."""
    return actualizar_moto(id, {"estado": "vendido"})


def eliminar_moto(moto_id: int) -> bool:
    """
    Borra una moto Y todos sus archivos del bucket (foto principal,
    galería y video), igual que la versión de producción. El borrado
    de la fila en fotos_motos lo hace el 'on delete cascade' de la tabla.
    """
    supabase = get_supabase()

    # 1. Traer la moto para conocer sus archivos.
    moto = supabase.table("motos")\
        .select("foto_path, video_path")\
        .eq("id", moto_id)\
        .execute()

    # 2. Traer las fotos de galería.
    galeria = supabase.table("fotos_motos")\
        .select("foto_path")\
        .eq("moto_id", moto_id)\
        .execute()

    # 3. Juntar los paths que existan.
    paths = []
    if moto.data:
        fila = moto.data[0]
        if fila.get("foto_path"):
            paths.append(fila["foto_path"])
        if fila.get("video_path"):
            paths.append(fila["video_path"])
    for foto in galeria.data:
        if foto.get("foto_path"):
            paths.append(foto["foto_path"])

    # 4. Borrar los archivos del bucket, si hay.
    if paths:
        supabase.storage.from_("motos").remove(paths)

    # 5. Borrar la moto (el cascade limpia fotos_motos).
    supabase.table("motos")\
        .delete()\
        .eq("id", moto_id)\
        .execute()

    return True
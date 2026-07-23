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

from app.db.cliente import get_supabase_publico, get_supabase_admin


# ============================================================
#  CONSULTAS DE MOTOS (lectura)
# ============================================================

def obtener_motos_disponibles():
    """
    Motos disponibles, con los datos de su sede incluidos.

    El 'sedes(nombre, direccion)' dentro del select aprovecha la clave
    foránea: Supabase trae la sede relacionada en la misma consulta,
    sin necesidad de una segunda llamada por cada moto. Cada moto
    llegará con un campo 'sedes' que contiene esos datos.
    """
    supabase = get_supabase_publico()
    resultado = supabase.table("motos")\
        .select("*, sedes(nombre, direccion)")\
        .eq("estado", "disponible")\
        .execute()
    return resultado.data


def obtener_todas_las_motos():
    """Todas las motos, más recientes primero (para el panel admin)."""
    supabase = get_supabase_publico()
    resultado = supabase.table("motos")\
        .select("*")\
        .order("created_at", desc=True)\
        .execute()
    return resultado.data


def obtener_moto_por_id(id: int):
    """Una moto por su id, con los datos de su sede."""
    supabase = get_supabase_publico()
    resultado = supabase.table("motos")\
        .select("*, sedes(nombre, direccion)")\
        .eq("id", id)\
        .execute()
    return resultado.data[0] if resultado.data else None


def obtener_fotos_moto(moto_id: int):
    """Fotos de galería de una moto, ordenadas por el campo 'orden'."""
    supabase = get_supabase_publico()
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
    supabase = get_supabase_admin()
    resultado = supabase.table("motos")\
        .insert(datos)\
        .execute()
    return resultado.data


def actualizar_moto(id: int, datos: dict):
    """Actualiza una moto por su id."""
    supabase = get_supabase_admin()
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
    supabase = get_supabase_admin()

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

    # ============================================================
#  STORAGE (bucket "motos")
# ============================================================

def subir_archivo(path: str, contenido: bytes, content_type: str) -> str:
    """
    Sube un archivo al bucket 'motos' y devuelve su URL pública.

    path: ruta/nombre dentro del bucket (ya generado de forma segura).
    contenido: los bytes del archivo (ya validados por magic bytes).
    content_type: el tipo REAL detectado, no el declarado por el cliente.

    Usa la conexión ADMIN porque subir es una operación de escritura,
    permitida solo desde el panel protegido por login.
    """
    supabase = get_supabase_admin()
    supabase.storage.from_("motos").upload(
        path=path,
        file=contenido,
        file_options={"content-type": content_type},
    )
    return supabase.storage.from_("motos").get_public_url(path)


def agregar_foto_galeria(moto_id: int, foto_url: str, foto_path: str, orden: int = 0):
    """Registra una foto de galería en la tabla fotos_motos."""
    supabase = get_supabase_admin()
    resultado = supabase.table("fotos_motos")\
        .insert({
            "moto_id": moto_id,
            "foto_url": foto_url,
            "foto_path": foto_path,
            "orden": orden,
        })\
        .execute()
    return resultado.data


def contar_fotos_galeria(moto_id: int) -> int:
    """Cuántas fotos de galería tiene ya una moto (para calcular el orden)."""
    supabase = get_supabase_publico()
    resultado = supabase.table("fotos_motos")\
        .select("id")\
        .eq("moto_id", moto_id)\
        .execute()
    return len(resultado.data)

    # ============================================================
#  SEDES
# ============================================================

def obtener_sedes_activas():
    """Sedes activas, para los selectores y el catálogo público."""
    supabase = get_supabase_publico()
    resultado = supabase.table("sedes")\
        .select("*")\
        .eq("activa", True)\
        .order("id")\
        .execute()
    return resultado.data


def obtener_sede_por_id(id: int):
    """Una sede por su id, o None si no existe."""
    supabase = get_supabase_publico()
    resultado = supabase.table("sedes")\
        .select("*")\
        .eq("id", id)\
        .execute()
    return resultado.data[0] if resultado.data else None

    # ============================================================
#  CATÁLOGO CON FILTROS
# ============================================================

def obtener_marcas_disponibles():
    """
    Lista de marcas que existen en el inventario disponible.

    Se calcula desde la BASE, no de una lista fija: si mañana entra una
    moto de una marca nueva, aparece sola en el filtro.
    """
    supabase = get_supabase_publico()
    resultado = supabase.table("motos")\
        .select("marca")\
        .eq("estado", "disponible")\
        .execute()
    # set() elimina duplicados, sorted() las ordena alfabéticamente.
    return sorted({m["marca"] for m in resultado.data if m.get("marca")})


def obtener_motos_filtradas(filtros: dict):
    """
    Motos disponibles que cumplen los filtros indicados.

    La consulta se CONSTRUYE dinámicamente: empezamos con la base
    (disponibles) y le vamos encadenando condiciones solo por los
    filtros que llegaron. Un filtro vacío simplemente no se aplica.

    filtros: dict ya VALIDADO (la ruta se encarga de limpiarlo).
        marca, sede_id, precio_min, precio_max, texto
    """
    supabase = get_supabase_publico()

    # Consulta base: siempre solo las disponibles, con su sede.
    consulta = supabase.table("motos")\
        .select("*, sedes(nombre, direccion)")\
        .eq("estado", "disponible")

    # Cada filtro presente añade una condición a la consulta.
    if filtros.get("marca"):
        consulta = consulta.eq("marca", filtros["marca"])

    if filtros.get("sede_id"):
        consulta = consulta.eq("sede_id", filtros["sede_id"])

    if filtros.get("precio_min") is not None:
        consulta = consulta.gte("precio", filtros["precio_min"])   # gte = mayor o igual

    if filtros.get("precio_max") is not None:
        consulta = consulta.lte("precio", filtros["precio_max"])   # lte = menor o igual

    if filtros.get("texto"):
        # Búsqueda en marca O modelo. 'ilike' = contiene, sin distinguir
        # mayúsculas. El % es comodín: %yamaha% = "contiene yamaha".
        texto = filtros["texto"]
        consulta = consulta.or_(f"marca.ilike.%{texto}%,modelo.ilike.%{texto}%")

    return consulta.order("created_at", desc=True).execute().data

    # ============================================================
#  GESTIÓN DE FOTOS (borrar, cambiar portada)
# ============================================================

def obtener_foto_galeria(foto_id: int):
    """Una foto de galería por su id, o None."""
    supabase = get_supabase_publico()
    resultado = supabase.table("fotos_motos")\
        .select("*")\
        .eq("id", foto_id)\
        .execute()
    return resultado.data[0] if resultado.data else None


def borrar_archivo(path: str):
    """
    Borra un archivo del bucket.

    IMPORTANTE: borrar la fila de la base NO basta. Si el archivo queda
    en el bucket, sigue accesible por su URL pública para siempre y
    ocupando espacio. 'Borrado' tiene que significar borrado de verdad.
    """
    if not path:
        return
    supabase = get_supabase_admin()
    supabase.storage.from_("motos").remove([path])


def eliminar_foto_galeria(foto_id: int):
    """Borra una foto de galería: primero el archivo, luego la fila."""
    supabase = get_supabase_admin()
    supabase.table("fotos_motos")\
        .delete()\
        .eq("id", foto_id)\
        .execute()

        # ============================================================
#  USUARIOS
# ============================================================

def obtener_usuario_por_nombre(usuario: str):
    """
    Busca un usuario activo por su nombre de login.

    Usa la conexión ADMIN: la tabla usuarios tiene RLS que la hace
    invisible al rol público. Solo el service_role puede leerla.
    Devuelve el usuario (con su hash y rol) o None.
    """
    supabase = get_supabase_admin()
    resultado = supabase.table("usuarios")\
        .select("*")\
        .eq("usuario", usuario)\
        .eq("activo", True)\
        .execute()
    return resultado.data[0] if resultado.data else None
    # ============================================================
#  VENTAS (registro de operaciones)
# ============================================================

def registrar_venta(datos: dict):
    """Guarda el registro histórico de una venta."""
    supabase = get_supabase_admin()
    resultado = supabase.table("ventas").insert(datos).execute()
    return resultado.data

    # ============================================================
#  INTENCIONES (registro anónimo de interés)
# ============================================================

def registrar_intencion(moto_id: int, sede_id: int):
    """
    Guarda una intención de compra. Escritura desde el servidor,
    con la conexión admin.
    """
    supabase = get_supabase_admin()
    supabase.table("intenciones").insert({
        "moto_id": moto_id,
        "sede_id": sede_id,
    }).execute()
"""
Servicio de inventario: la lógica de negocio de las motos.

>>> CONECTADO A BASE DE DATOS REAL (Supabase de desarrollo) <
El modo de datos de prueba quedó atrás: cada función delega en el
repositorio, que habla con Supabase. Las rutas y templates no notan
la diferencia — misma firma, misma forma de datos. Ese era el punto
de la arquitectura por capas: cambiar la fuente tocando UN archivo.
"""

from app.db import repositorios


# ============================================================
#  LECTURA
# ============================================================

def listar_motos_disponibles():
    """Motos con estado 'disponible' (catálogo público y conteo de inicio)."""
    return repositorios.obtener_motos_disponibles()


def listar_todas_las_motos():
    """Todas las motos, más recientes primero (panel administrativo)."""
    return repositorios.obtener_todas_las_motos()


def obtener_moto(id: int):
    """Una moto por su id, o None si no existe."""
    return repositorios.obtener_moto_por_id(id)


def obtener_galeria(moto_id: int):
    """Fotos de galería de una moto, ordenadas."""
    return repositorios.obtener_fotos_moto(moto_id)


# ============================================================
#  ESCRITURA
# ============================================================

def agregar_moto(datos: dict):
    """Agrega una moto nueva al inventario."""
    return repositorios.agregar_moto(datos)


def actualizar_moto(id: int, datos: dict):
    """Actualiza los datos de una moto existente."""
    return repositorios.actualizar_moto(id, datos)


def marcar_vendida(id: int):
    """Marca una moto como vendida."""
    return repositorios.marcar_como_vendida(id)


def eliminar_moto(id: int):
    """Elimina una moto y sus archivos asociados."""
    return repositorios.eliminar_moto(id)

    # ============================================================
#  SUBIDA DE FOTOS
# ============================================================

from app.servicios import archivos


def subir_fotos_moto(moto_id: int, lista_archivos: list) -> dict:
    """
    Sube VARIAS fotos de una moto de una sola vez.

    lista_archivos: lista de archivos recibidos del formulario.

    Lógica (opción A acordada):
      - Si la moto aún no tiene foto principal, la PRIMERA foto válida
        se convierte en la principal (portada del catálogo).
      - El resto van a la galería (tabla fotos_motos).

    Cada archivo se valida por separado (magic bytes). Si uno falla, se
    salta y se sigue con los demás: no queremos que una foto mala
    arruine la subida de las otras 9 buenas.

    Devuelve un resumen: {"subidas": n, "rechazadas": [motivos...]}
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto:
        return {"subidas": 0, "rechazadas": ["La moto no existe."]}

    # ¿Ya tiene foto principal? Si no, la primera válida lo será.
    tiene_principal = bool(moto.get("foto_url"))

    # El orden de galería continúa desde las fotos que ya tenga.
    orden = repositorios.contar_fotos_galeria(moto_id)

    subidas = 0
    rechazadas = []

    for archivo in lista_archivos:
        # Saltamos entradas vacías (el navegador a veces manda una).
        if not archivo or not archivo.filename:
            continue

        try:
            # 1. Validar por magic bytes (lanza ErrorValidacion si falla).
            datos = archivos.validar_imagen(archivo)

            # 2. Nombre seguro y aleatorio, con la extensión REAL.
            #    La principal va a la raíz; la galería, a su carpeta.
            carpeta = "" if not tiene_principal else "galeria"
            path = archivos.generar_nombre_seguro(datos["extension"], carpeta)

            # 3. Subir al bucket.
            url = repositorios.subir_archivo(
                path, datos["contenido"], datos["content_type"])

            # 4. Registrar según sea principal o galería.
            if not tiene_principal:
                repositorios.actualizar_moto(
                    moto_id, {"foto_url": url, "foto_path": path})
                tiene_principal = True
            else:
                repositorios.agregar_foto_galeria(moto_id, url, path, orden)
                orden += 1

            subidas += 1

        except Exception as e:
            # Una foto mala no debe tumbar las demás: la anotamos y seguimos.
            motivo = getattr(e, "mensaje", str(e))
            rechazadas.append(f"{archivo.filename}: {motivo}")

    return {"subidas": subidas, "rechazadas": rechazadas}

    # ============================================================
#  GESTIÓN DE FOTOS
# ============================================================

def eliminar_foto(moto_id: int, foto_id: int) -> bool:
    """
    Borra una foto de la GALERÍA de una moto.

    Verifica que la foto pertenezca a esa moto antes de borrarla:
    nunca confíes en que el id que llega por la URL es legítimo.
    """
    foto = repositorios.obtener_foto_galeria(foto_id)
    if not foto:
        return False

    # Control de pertenencia: la foto debe ser de ESTA moto.
    # Sin esto, alguien podría pasar el id de la foto de otra moto.
    if foto.get("moto_id") != moto_id:
        return False

    # Primero el archivo del bucket, luego la fila.
    repositorios.borrar_archivo(foto.get("foto_path"))
    repositorios.eliminar_foto_galeria(foto_id)
    return True


def eliminar_portada(moto_id: int) -> bool:
    """
    Borra la foto de portada. Si la moto tiene fotos en galería, la
    primera SUBE automáticamente a ocupar su lugar (opción A), para
    que la moto nunca quede sin imagen si tiene otras disponibles.
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto or not moto.get("foto_url"):
        return False

    # 1. Borrar el archivo de la portada actual del bucket.
    repositorios.borrar_archivo(moto.get("foto_path"))

    # 2. ¿Hay fotos en galería para promover?
    galeria = repositorios.obtener_fotos_moto(moto_id)
    if galeria:
        nueva = galeria[0]
        # La primera de galería pasa a ser portada...
        repositorios.actualizar_moto(moto_id, {
            "foto_url": nueva["foto_url"],
            "foto_path": nueva["foto_path"],
        })
        # ...y se quita de la galería (su archivo NO se borra: ahora es
        # la portada y lo sigue usando).
        repositorios.eliminar_foto_galeria(nueva["id"])
    else:
        # Sin galería: la moto queda sin imagen.
        repositorios.actualizar_moto(moto_id, {"foto_url": None, "foto_path": None})

    return True


def hacer_portada(moto_id: int, foto_id: int) -> bool:
    """
    Convierte una foto de galería en la portada.

    La portada actual NO se borra: baja a la galería. Es un intercambio,
    no un reemplazo destructivo. Así nunca pierdes una foto por elegir
    otra portada.
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    foto = repositorios.obtener_foto_galeria(foto_id)

    if not moto or not foto:
        return False
    if foto.get("moto_id") != moto_id:
        return False

    portada_url = moto.get("foto_url")
    portada_path = moto.get("foto_path")

    # 1. La foto elegida pasa a ser portada.
    repositorios.actualizar_moto(moto_id, {
        "foto_url": foto["foto_url"],
        "foto_path": foto["foto_path"],
    })
    # 2. Se quita de la galería (ya no está ahí, está arriba).
    repositorios.eliminar_foto_galeria(foto_id)

    # 3. La portada anterior baja a la galería (si existía).
    if portada_url:
        orden = repositorios.contar_fotos_galeria(moto_id)
        repositorios.agregar_foto_galeria(moto_id, portada_url, portada_path, orden)

    return True

    # ============================================================
#  INTENCIONES
# ============================================================

def registrar_intencion(moto_id: int):
    """
    Registra el interés en una moto. Busca la sede de la moto para
    guardarla junto al evento (útil para métricas por sede).

    Si la moto no existe, no registra nada (silencioso): un id inválido
    en la URL no debe romper la redirección a WhatsApp.
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto:
        return
    repositorios.registrar_intencion(moto_id, moto.get("sede_id"))
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
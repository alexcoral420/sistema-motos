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
#  REGISTRO DE VENTAS
# ============================================================

def registrar_venta(moto_id: int, usuario_id: int, usuario_nombre: str):
    """
    Deja constancia histórica de una venta.

    Congela la descripción de la moto (marca modelo año) y el nombre
    del vendedor como TEXTO, para que el reporte siga siendo legible
    aunque después se borre la moto o cambie el usuario.
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto:
        return

    # "YAMAHA Fazer 2026" — se arma aquí y se guarda tal cual.
    partes = [moto.get("marca") or "", moto.get("modelo") or ""]
    if moto.get("anio"):
        partes.append(str(moto["anio"]))
    descripcion = " ".join(p for p in partes if p).strip()

    repositorios.registrar_venta({
        "moto_id": moto_id,
        "descripcion": descripcion,
        "placa": moto.get("placa"),
        "usuario_id": usuario_id,
        "usuario_nombre": usuario_nombre,
        "sede_id": moto.get("sede_id"),
    })

    # ============================================================
#  COMPRAS (asesor compra una moto a un particular)
# ============================================================

def comprar_moto(datos: dict, usuario_id: int, usuario_nombre: str):
    """
    Flujo de compra (Opción A): agrega la moto al inventario Y
    registra la compra en un solo paso.

    'datos' viene del formulario (marca, modelo, precio, etc.).
    'usuario_id' y 'usuario_nombre' vienen SIEMPRE de la sesión,
    nunca del formulario: la identidad la pone el servidor.
    """
    # 1. Agregar la moto al inventario (reutiliza la lógica existente).
    moto = repositorios.agregar_moto(datos)
    if not moto:
        return None

    # agregar_moto devuelve una lista; la moto creada es el primer elemento.
    moto_creada = moto[0] if isinstance(moto, list) else moto
    moto_id = moto_creada["id"]

    # 2. Congelar la descripción como TEXTO (mismo patrón que registrar_venta).
    partes = [moto_creada.get("marca") or "", moto_creada.get("modelo") or ""]
    if moto_creada.get("anio"):
        partes.append(str(moto_creada["anio"]))
    descripcion = " ".join(p for p in partes if p).strip()

    # 3. Registrar la compra con la identidad del asesor (de sesión).
    repositorios.registrar_compra({
        "moto_id": moto_id,
        "descripcion": descripcion,
        "placa": moto_creada.get("placa"),
        "usuario_id": usuario_id,
        "usuario_nombre": usuario_nombre,

    })

    return moto_creada

def _describir_moto(moto: dict) -> str:
    """
    Congela la descripción de la moto (marca modelo año), su placa y el
    nombre del vendedor como TEXTO, para que el reporte siga siendo legible
    aunque después se borre la moto o cambie el usuario.
    Se guarda como texto en compras/ventas/permutas para que el
    reporte siga legible aunque después se borre la moto.
    """
    partes = [moto.get("marca") or "", moto.get("modelo") or ""]
    if moto.get("anio"):
        partes.append(str(moto["anio"]))
    return " ".join(p for p in partes if p).strip()

    # ============================================================
#  PERMUTAS (asesor cierra compra + venta en una negociación)
# ============================================================

def registrar_permuta(datos_entrante: dict, placa_saliente: str,
                       usuario_id: int, usuario_nombre: str):
    """
    Cierra una permuta: el cliente entrega una moto (entrante) y se
    lleva una del inventario (saliente), en una sola negociación.

    Hace TRES operaciones:
      1. Crea la moto entrante en el inventario.
      2. Marca la moto saliente como vendida.
      3. Registra la permuta (enlaza ambas motos + asesor).

    Estrategia de atomicidad: validamos la placa saliente ANTES de
    escribir nada. Si la placa no corresponde a una moto disponible,
    salimos sin haber tocado la base. Así el único error probable
    (placa mal tecleada) se detecta antes de la primera escritura.

    Devuelve la moto entrante creada, o None si la placa no es válida.
    La identidad del asesor sale SIEMPRE de la sesión, nunca del form.
    """
    # --- VALIDAR PRIMERO (antes de escribir nada) ---
    # La placa se normaliza a mayúsculas para que el match exacto
    # funcione aunque el asesor la escriba en minúsculas.
    placa_saliente = placa_saliente.strip().upper()
    moto_saliente = repositorios.obtener_disponible_por_placa(placa_saliente)
    if not moto_saliente:
        # No existe una moto disponible con esa placa: abortamos limpio.
        return None

    # --- ESCRIBIR DESPUÉS (la validación ya pasó) ---
    # 1. Crear la moto entrante (reutiliza la lógica de inventario).
    moto = repositorios.agregar_moto(datos_entrante)
    moto_entrante = moto[0] if isinstance(moto, list) else moto

    # 2. Marcar la moto saliente como vendida.
    repositorios.marcar_como_vendida(moto_saliente["id"])

    # 3. Congelar descripciones de ambas motos (mismo patrón que ventas).
    descripcion_entrante = _describir_moto(moto_entrante)
    descripcion_saliente = _describir_moto(moto_saliente)

    # 4. Registrar la permuta con la identidad del asesor (de sesión).
    repositorios.registrar_permuta({
        "moto_entrante_id": moto_entrante["id"],
        "moto_saliente_id": moto_saliente["id"],
        "descripcion_entrante": descripcion_entrante,
        "descripcion_saliente": descripcion_saliente,
        "usuario_id": usuario_id,
        "usuario_nombre": usuario_nombre,
    })

    return moto_entrante
    
    # ============================================================
#  INTENCIONES
# ============================================================

def registrar_intencion(moto_id: int, sesion_id: str = None):
    """
    Registra el interés en una moto (clic en 'Preguntar por esta moto').
    Si la moto no existe, no registra nada: un id inválido en la URL no
    debe romper la redirección a WhatsApp.
    """
    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto:
        return
        
    print(f"DEBUG: llamando al repositorio")
    repositorios.registrar_intencion(moto_id, moto.get("sede_id"), sesion_id)
    print(f"DEBUG: insert ejecutado")
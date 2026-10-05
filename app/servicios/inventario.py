"""
Servicio de inventario: la lógica de negocio de las motos.

>>> CONECTADO A BASE DE DATOS REAL (Supabase de desarrollo) <
El modo de datos de prueba quedó atrás: cada función delega en el
repositorio, que habla con Supabase. Las rutas y templates no notan
la diferencia — misma firma, misma forma de datos. Ese era el punto
de la arquitectura por capas: cambiar la fuente tocando UN archivo.
"""

from datetime import datetime, timezone

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger
from app.seguridad import validadores
from app.servicios import sedes
from app.servicios.contratos import moto_en_alcance


# Estados posibles de una moto: fuente única para validación, filtros
# del panel y vista pública. DEBE coincidir con el CHECK
# motos_estado_check de la migración 010 (ciclo de publicación).
ESTADOS_MOTO = ("por_publicar", "disponible", "reservado", "vendido")
# Subconjunto de ESTADOS_MOTO visible al público (detalle de moto).
ESTADOS_VISIBLES_PUBLICO = ("disponible", "reservado", "vendido")
# Estados que se pueden elegir al editar. 'por_publicar' NO es editable:
# solo se sale de él con publicar_moto (que valida foto y precio).
ESTADOS_EDITABLES = ("disponible", "reservado", "vendido")


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


def obtener_moto_publica(id: int):
    """Una moto por su id para la vista pública, o None si no existe
    o si su estado no está en ESTADOS_VISIBLES_PUBLICO."""
    moto = repositorios.obtener_moto_por_id(id)
    if not moto or moto.get("estado") not in ESTADOS_VISIBLES_PUBLICO:
        return None
    return moto


def obtener_galeria(moto_id: int):
    """Fotos de galería de una moto, ordenadas."""
    return repositorios.obtener_fotos_moto(moto_id)


# ============================================================
#  ESCRITURA
# ============================================================

def validar_datos_moto(form, estado: str, exigir_precio: bool = True) -> dict:
    """
    Valida y normaliza los datos de una moto que llegan de un formulario
    (agregar, comprar, permuta, editar). Fuente única de las reglas.

    El estado NO lo decide esta función: lo pasa quien llama, ya
    validado. Devuelve el dict listo para guardar. Lanza ErrorValidacion
    si cualquier campo no cumple, sin construir datos a medias.

    exigir_precio=False: el precio es opcional (en una compra todavía
    no hay precio de venta; se define al publicar).
    """
    datos = {
        "marca": validadores.validar_texto(
            form.get("marca"), "marca", min_len=1, max_len=50),
        "modelo": validadores.validar_texto(
            form.get("modelo"), "modelo", min_len=1, max_len=50),
        "anio": validadores.validar_entero(
            form.get("anio"), "año", minimo=1950, maximo=2100),
        "cilindraje": validadores.validar_entero(
            form.get("cilindraje"), "cilindraje", minimo=90, maximo=1200),
        "color": validadores.validar_texto(
            form.get("color"), "color", min_len=1, max_len=30),
        "precio": validadores.validar_entero(
            form.get("precio"), "precio", minimo=0, maximo=999999999,
            obligatorio=exigir_precio),
        "kilometraje": validadores.validar_entero(
            form.get("kilometraje"), "kilometraje", minimo=0, maximo=9999999),
        "estado": estado,
        "sede_id": validadores.validar_entero(
            form.get("sede_id"), "sede", minimo=1),
        "descripcion": validadores.validar_texto(
            form.get("descripcion"), "descripción",
            max_len=1000, obligatorio=False) or "",
        "soat": validadores.validar_texto(
            form.get("soat"), "soat", max_len=20, obligatorio=False),
        "tecno": validadores.validar_texto(
            form.get("tecno"), "tecno", max_len=20, obligatorio=False),
        "placa": validadores.validar_texto(
            form.get("placa"), "placa", max_len=10, obligatorio=False),
    }
    # Lista blanca DINÁMICA: la sede debe existir de verdad en la
    # base. Si mañana agregas una sede, se acepta sola.
    if str(datos["sede_id"]) not in sedes.ids_validos():
        raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
    # Normalizamos a mayúsculas para consistencia de datos.
    datos["marca"] = datos["marca"].upper()
    datos["modelo"] = datos["modelo"].upper()
    if datos["placa"]:
        datos["placa"] = datos["placa"].upper()
    return datos


def agregar_moto(datos: dict):
    """Agrega una moto nueva al inventario."""
    return repositorios.agregar_moto(datos)


def actualizar_moto(id: int, datos: dict):
    """Actualiza los datos de una moto existente."""
    return repositorios.actualizar_moto(id, datos)


def publicar_moto(id: int):
    """
    Publica una moto: pasa de 'por_publicar' a 'disponible' y registra
    publicada_en. Valida existencia, alcance de sede (moto_en_alcance),
    estado y que tenga foto y precio. Lanza ErrorValidacion si no.
    """
    moto = repositorios.obtener_moto_por_id(id)
    if not moto:
        raise ErrorValidacion("La moto no existe.")

    if moto_en_alcance(id) is None:
        raise ErrorValidacion("La moto está fuera del alcance de tu sede.")

    if moto.get("estado") != "por_publicar":
        raise ErrorValidacion(
            f"Solo se pueden publicar motos pendientes (estado actual: "
            f"'{moto.get('estado')}').")

    faltantes = []
    if not moto.get("foto_url"):
        faltantes.append("foto de portada")
    if not moto.get("precio") or moto["precio"] <= 0:
        faltantes.append("precio mayor a cero")
    if faltantes:
        raise ErrorValidacion(
            "No se puede publicar: falta " + " y ".join(faltantes) + ".")

    # El WHERE incluye estado = 'por_publicar': si dos personas publican
    # a la vez, solo una actualiza; la otra no encuentra la fila.
    filas = repositorios.actualizar_moto_si_estado(id, "por_publicar", {
        "estado": "disponible",
        "publicada_en": datetime.now(timezone.utc).isoformat(),
    })
    if not filas:
        raise ErrorValidacion("La moto ya no estaba pendiente de publicar.")


ESTADOS_VENDIBLES = ("disponible", "reservado")


def moto_para_vender(id: int) -> dict:
    """
    La moto, si el usuario en sesión puede venderla: existe, está en el
    alcance de su sede y en un estado vendible. Lanza ErrorValidacion
    con un mensaje claro si no.

    El id viene de la URL y se puede editar: sin estas validaciones un
    usuario de una sede podría vender motos de otra. El alcance reutiliza
    moto_en_alcance (contratos.py), que usa la sede de la SESIÓN.
    """
    moto = repositorios.obtener_moto_por_id(id)
    if not moto:
        raise ErrorValidacion("La moto no existe.")

    if moto_en_alcance(id) is None:
        raise ErrorValidacion("La moto está fuera del alcance de tu sede.")

    if moto.get("estado") not in ESTADOS_VENDIBLES:
        raise ErrorValidacion(
            f"La moto no se puede vender en estado '{moto.get('estado')}'.")
    return moto


def asesores_para_venta(moto: dict) -> list:
    """Asesores activos de la sede de la moto, para el selector."""
    return repositorios.listar_asesores_activos(moto.get("sede_id"))


def _validar_asesor_de_venta(asesor_id, sede_id: int) -> dict:
    """El asesor existe, es asesor, está activo y es de la sede de la moto."""
    asesor_id = validadores.validar_entero(asesor_id, "asesor", minimo=1)
    asesor = repositorios.obtener_usuario_por_id(asesor_id)
    if (not asesor
            or asesor.get("rol") != "asesor"
            or not asesor.get("activo")
            or asesor.get("sede_id") != sede_id):
        raise ErrorValidacion("El asesor elegido no es válido para la sede de esta moto.",
                              "asesor")
    return asesor


def vender_moto(id: int, usuario_id: int, usuario_nombre: str, rol: str,
                asesor_id=None) -> int:
    """
    Vende una moto y devuelve el id de la venta.

    En Python se valida lo que da mensajes claros: la moto
    (moto_para_vender) y el asesor. usuario_* (quién registra) y rol
    vienen de la SESIÓN. Si quien vende es asesor, el asesor es él
    mismo y se ignora cualquier asesor_id. El nombre del asesor sale de
    la base, nunca del formulario.

    Marcar vendida y crear la venta es UNA llamada a la función
    registrar_venta_moto (migración 015), que bloquea la moto: dos
    clics simultáneos ya no pueden venderla dos veces.
    """
    moto = moto_para_vender(id)

    if rol == "asesor":
        asesor_id = usuario_id
    asesor = _validar_asesor_de_venta(asesor_id, moto.get("sede_id"))

    return repositorios.registrar_venta_moto(
        id, usuario_id, usuario_nombre, asesor["id"], asesor.get("nombre_completo"))


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

    # 3. Registrar la compra con la identidad de sesión. usuario_* = quién
    #    registró; asesor_* = quién hizo el negocio. Hoy son la misma persona.
    #    Sin transacción todavía: si el registro falla, la moto ya quedó en
    #    inventario sin su fila en 'compras'. Mismo patrón que vender_moto.
    try:
        registrada = repositorios.registrar_compra({
            "moto_id": moto_id,
            "descripcion": descripcion,
            "placa": moto_creada.get("placa"),
            "usuario_id": usuario_id,
            "usuario_nombre": usuario_nombre,
            "asesor_id": usuario_id,
            "asesor_nombre": usuario_nombre,
            "sede_id": moto_creada.get("sede_id"),
        })
    except Exception:
        obtener_logger().exception(
            "INCONSISTENCIA: moto id=%s creada en inventario pero falló "
            "registrar_compra (usuario_id=%s, usuario=%s). Corregir a mano.",
            moto_id, usuario_id, usuario_nombre)
        raise

    if not registrada:
        obtener_logger().error(
            "INCONSISTENCIA: moto id=%s creada en inventario pero "
            "registrar_compra no devolvió fila (usuario_id=%s, usuario=%s). "
            "Corregir a mano.",
            moto_id, usuario_id, usuario_nombre)

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

def obtener_similares(moto, limite=15):
    """
    Motos para sugerir en el detalle, ordenadas por relevancia.

    La regla de 'que es parecido' vive aca (negocio), no en el repositorio
    (datos):
    1. Presupuesto = restriccion dura: solo motos en precio ±50% (el repo).
    2. Dentro del presupuesto se prioriza MISMA MARCA; como desempate, la
       mas cercana en precio. En este catalogo casi todo cae entre 7 y 11M,
       asi que el precio casi no discrimina: la marca es la senal util.
    La marca NO filtra (no excluye otras marcas), solo ordena: asi la
    seccion no queda vacia cuando hay pocas motos de esa marca.
    """
    if not moto:
        return []

    candidatas = repositorios.obtener_motos_similares(moto["id"], moto.get("precio"))
    precio_obj = moto.get("precio") or 0
    marca_obj = (moto.get("marca") or "").strip().lower()

    def clave(m):
        misma_marca = (m.get("marca") or "").strip().lower() == marca_obj
        cercania = abs((m.get("precio") or 0) - precio_obj)
        # (0 antes que 1) -> misma marca primero; luego menor dif. de precio.
        return (0 if misma_marca else 1, cercania)

    candidatas.sort(key=clave)
    return candidatas[:limite]
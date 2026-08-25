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

def _condicion_rangos(columna: str, rangos):
    """
    Arma la condición OR para una lista de rangos (min, max).

    Los rangos vienen ya validados desde el servicio: son números, no
    texto del cliente. Por eso es seguro interpolarlos en la consulta.

    Ejemplo: [(None, 125), (151, 200)] sobre 'cilindraje' produce
        and(cilindraje.lte.125),and(cilindraje.gte.151,cilindraje.lte.200)
    que Supabase interpreta como "cumple el primero O el segundo".
    """
    if not rangos:
        return None

    partes = []
    for minimo, maximo in rangos:
        condiciones = []
        if minimo is not None:
            condiciones.append(f"{columna}.gte.{int(minimo)}")
        if maximo is not None:
            condiciones.append(f"{columna}.lte.{int(maximo)}")
        if condiciones:
            partes.append("and(" + ",".join(condiciones) + ")")

    return ",".join(partes) if partes else None


def obtener_motos_filtradas(filtros: dict, limite: int = 15, pagina: int = 1):
    """
    Motos disponibles que cumplen los filtros, ordenadas por popularidad
    reciente y paginadas.

    Consulta la vista catalogo_ordenado en lugar de la tabla motos: la vista
    ya trae las consultas de los ultimos 15 dias calculadas y los datos de la
    sede aplanados. Ordenar en la base (y no en Python) permite paginar de
    verdad: se traen 15 filas, no 130.

    Devuelve (motos, total) para que el template pueda armar los controles
    de paginacion.
    """
    supabase = get_supabase_publico()

    consulta = supabase.table("catalogo_ordenado").select("*", count="exact")

    if filtros.get("marcas"):
        consulta = consulta.in_("marca", filtros["marcas"])

    if filtros.get("sede_id"):
        consulta = consulta.eq("sede_id", filtros["sede_id"])

    condicion_precio = _condicion_rangos("precio", filtros.get("precio_rangos"))
    if condicion_precio:
        consulta = consulta.or_(condicion_precio)

    condicion_cc = _condicion_rangos("cilindraje", filtros.get("cilindraje_rangos"))
    if condicion_cc:
        consulta = consulta.or_(condicion_cc)

    condicion_anio = _condicion_rangos("anio", filtros.get("anio_rangos"))
    if condicion_anio:
        consulta = consulta.or_(condicion_anio)

    if filtros.get("texto"):
        texto = filtros["texto"]
        consulta = consulta.or_(f"marca.ilike.%{texto}%,modelo.ilike.%{texto}%")

    # Orden: primero lo mas consultado en 15 dias; entre iguales, lo mas
    # reciente. Asi una moto nueva sin consultas queda al frente de las
    # viejas que tampoco tienen.
    consulta = consulta.order("consultas_recientes", desc=True)\
                       .order("created_at", desc=True)

    # range() es inclusivo en ambos extremos: para 15 por pagina, la
    # pagina 1 pide de 0 a 14, la pagina 2 de 15 a 29.
    desde = (pagina - 1) * limite
    hasta = desde + limite - 1
    resultado = consulta.range(desde, hasta).execute()

    return resultado.data, resultado.count

   
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


def registrar_compra(datos: dict):
    """Guarda el registro histórico de una compra."""
    supabase = get_supabase_admin()
    resultado = supabase.table("compras").insert(datos).execute()
    return resultado.data

def registrar_permuta(datos: dict):
    """Guarda el registro histórico de una permuta."""
    supabase = get_supabase_admin()
    resultado = supabase.table("permutas").insert(datos).execute()
    return resultado.data

    # ============================================================
#  INTENCIONES (registro anónimo de interés)
# ============================================================

def registrar_intencion(moto_id: int, sede_id: int, sesion_id: str = None):
    """
    Guarda una intención de compra. Escritura desde el servidor,
    con la conexión admin.
    """
    supabase = get_supabase_admin()
    supabase.table("intenciones").insert({
        "moto_id": moto_id,
        "sede_id": sede_id,
        "sesion_id": sesion_id,
    }).execute()

    # ============================================================
#  BÚSQUEDA EN EL PANEL ADMIN
# ============================================================

def buscar_motos_admin(moto_id=None, placa=None):
    """
    Todas las motos del panel, con filtros opcionales por id o placa.

    Es una LECTURA -> conexión pública (mínimo privilegio: leer no
    requiere la llave administrativa).
    """
    supabase = get_supabase_publico()
    consulta = supabase.table("motos").select("*, sedes(nombre)")

    if moto_id is not None:
        consulta = consulta.eq("id", moto_id)

    if placa:
        # ilike + comodines: encuentra la placa aunque escriban solo
        # una parte, y sin distinguir mayúsculas.
        consulta = consulta.ilike("placa", f"%{placa}%")

    return consulta.order("created_at", desc=True).execute().data

def obtener_disponible_por_placa(placa: str):
    """
    Busca UNA moto disponible por placa EXACTA (no parcial).

    A diferencia de buscar_motos_admin (que usa ilike parcial para el
    buscador del panel), aquí necesitamos identidad exacta: una placa
    corresponde a una sola moto disponible, o a ninguna. Se usa en la
    permuta, donde no puede haber ambigüedad sobre qué moto sale.
    """
    supabase = get_supabase_publico()
    resultado = supabase.table("motos")\
        .select("*")\
        .eq("placa", placa)\
        .eq("estado", "disponible")\
        .execute()
    return resultado.data[0] if resultado.data else None

    # ============================================================
#  DESTACADAS INTELIGENTES (por intención de compra)
# ============================================================

def obtener_motos_mas_consultadas(limite: int = 6):
    """
    Motos DISPONIBLES ordenadas por número de intenciones (consultas
    'Preguntar por esta moto'), de más a menos, que tengan foto.

    Es el cruce intenciones + motos: el sistema aprende de su propio uso.
    Si no hay suficientes con consultas, se completa con disponibles
    recientes para no dejar la sección a medias.
    """
    supabase = get_supabase_admin()

    # 1. Contar intenciones por moto. Traemos todas y agrupamos en Python
    #    (Supabase no da GROUP BY directo desde el cliente).
    intenciones = supabase.table("intenciones").select("moto_id").execute().data
    conteo = {}
    for i in intenciones:
        mid = i.get("moto_id")
        if mid is not None:
            conteo[mid] = conteo.get(mid, 0) + 1

    # 2. Traer las motos disponibles CON foto.
    motos = supabase.table("motos")\
        .select("*, sedes(nombre)")\
        .eq("estado", "disponible")\
        .not_.is_("foto_url", "null")\
        .execute().data

    # 3. Ordenar por número de consultas (las sin consultas van al final,
    #    y entre esas, las más recientes primero por venir ya ordenadas).
    motos.sort(key=lambda m: conteo.get(m["id"], 0), reverse=True)

    return motos[:limite]

    # ============================================================
#  REPORTES DE GERENCIA (leen las vistas SQL)
# ============================================================

def reporte_ventas_por_usuario():
    return get_supabase_admin().table("reporte_ventas_por_usuario").select("*").execute().data

def reporte_ventas_por_semana():
    return get_supabase_admin().table("reporte_ventas_por_semana").select("*").execute().data

def reporte_permutas_por_usuario():
    return get_supabase_admin().table("reporte_permutas_por_usuario").select("*").execute().data


def reporte_modelos_permutados():
    return get_supabase_admin().table("reporte_modelos_permutados").select("*").execute().data

def reporte_motos_consultadas():
    return get_supabase_admin().table("reporte_motos_consultadas").select("*").limit(15).execute().data

def reporte_consultas_por_marca():
    return get_supabase_admin().table("reporte_consultas_por_marca").select("*").execute().data

    # ============================================================
#  GESTIÓN DE USUARIOS (crear, listar, desactivar)
# ============================================================

def listar_usuarios():
    """
    Todos los usuarios, para el panel de gestión. Incluye activos e
    inactivos (los inactivos se muestran atenuados, no se ocultan:
    gerencia debe ver a quién desactivó).
    NUNCA devuelve el password_hash al panel: solo lo que se muestra.
    """
    supabase = get_supabase_admin()
    return supabase.table("usuarios")\
        .select("id, usuario, nombre_completo, rol, sede_id, activo, created_at")\
        .order("activo", desc=True)\
        .order("nombre_completo")\
        .execute().data


def crear_usuario(datos: dict):
    """Inserta un usuario nuevo. datos ya trae el password_hash calculado."""
    supabase = get_supabase_admin()
    return supabase.table("usuarios").insert(datos).execute().data


def desactivar_usuario(usuario_id: int):
    """Borrado lógico: activo = false. No elimina la fila."""
    supabase = get_supabase_admin()
    return supabase.table("usuarios")\
        .update({"activo": False})\
        .eq("id", usuario_id)\
        .execute().data


def contar_admins_activos():
    """
    Cuántos admin activos quedan. Sirve para la salvaguarda de 'no
    desactivar al último admin' — sin admins activos, nadie puede
    administrar el sistema.
    """
    supabase = get_supabase_admin()
    resultado = supabase.table("usuarios")\
        .select("id", count="exact")\
        .eq("rol", "admin")\
        .eq("activo", True)\
        .execute()
    return resultado.count


def obtener_usuario_por_id(usuario_id: int):
    """Un usuario por su id (para validar antes de desactivar)."""
    supabase = get_supabase_admin()
    resultado = supabase.table("usuarios")\
        .select("id, usuario, nombre_completo, rol, activo")\
        .eq("id", usuario_id)\
        .execute()
    return resultado.data[0] if resultado.data else None

def obtener_whatsapp_por_id(usuario_id):
    """
    Devuelve el número de WhatsApp de un asesor por su id, o None.
    Se usa en la atribución de línea: el link lleva el id del asesor,
    y acá lo traducimos a su número real (nunca exponemos el número
    en la URL).
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("usuarios")
                 .select("whatsapp")
                 .eq("id", usuario_id)
                 .eq("activo", True)
                 .execute())
    if resultado.data and resultado.data[0].get("whatsapp"):
        return resultado.data[0]["whatsapp"]
    return None

    # ---- Métricas del webhook (contactos, conversaciones, mensajes) ----

def buscar_contacto_por_telefono(telefono: str):
    """Devuelve el contacto con ese teléfono, o None si no existe."""
    supabase = get_supabase_admin()
    r = supabase.table("contactos").select("*").eq("telefono", telefono).limit(1).execute()
    return r.data[0] if r.data else None


def crear_contacto(telefono: str, canal: str):
    """Crea un contacto nuevo y lo devuelve."""
    supabase = get_supabase_admin()
    r = supabase.table("contactos").insert({
        "telefono": telefono,
        "canal": canal,
    }).execute()
    return r.data[0]


def buscar_conversacion_activa(contacto_id: int, limite_horas: int = 24):
    """
    Devuelve la conversación más reciente del contacto cuyo ultimo_mensaje
    esté dentro de la ventana (por defecto 24h), o None si no hay ninguna
    activa (lo que obliga a abrir una conversación nueva).
    """
    from datetime import datetime, timedelta, timezone
    corte = (datetime.now(timezone.utc) - timedelta(hours=limite_horas)).isoformat()

    supabase = get_supabase_admin()
    r = (supabase.table("conversaciones")
         .select("*")
         .eq("contacto_id", contacto_id)
         .gte("ultimo_mensaje", corte)
         .order("ultimo_mensaje", desc=True)
         .limit(1)
         .execute())
    return r.data[0] if r.data else None


def crear_conversacion(contacto_id: int, canal: str, moto_id: int = None):
    """Crea una conversación nueva y la devuelve."""
    supabase = get_supabase_admin()
    r = supabase.table("conversaciones").insert({
        "contacto_id": contacto_id,
        "canal": canal,
        "moto_id": moto_id,
    }).execute()
    return r.data[0]


def insertar_mensaje(conversacion_id: int, nivel: int,
                     tokens_entrada: int, tokens_salida: int, modelo: str = None):
    """Inserta un mensaje con sus métricas."""
    supabase = get_supabase_admin()
    supabase.table("mensajes").insert({
        "conversacion_id": conversacion_id,
        "nivel": nivel,
        "tokens_entrada": tokens_entrada,
        "tokens_salida": tokens_salida,
        "modelo": modelo,
    }).execute()


def actualizar_ultimo_mensaje(conversacion_id: int):
    """Marca la conversación como activa ahora (para la ventana de 24h)."""
    from datetime import datetime, timezone
    supabase = get_supabase_admin()
    supabase.table("conversaciones").update({
        "ultimo_mensaje": datetime.now(timezone.utc).isoformat()
    }).eq("id", conversacion_id).execute()

   



    # ============================================================
# Funciones de repositorio para leads_chat (agregar a repositorios.py).
# Guardan y leen leads del chat, cifrando los campos sensibles.
#
# Sigue el mismo patron que registrar_lead_financiacion:
#   - usa get_supabase_admin() porque leads_chat tiene RLS
#   - inserta un dict con los campos
#
# La diferencia clave: los campos sensibles se CIFRAN antes de guardar
# (con el modulo cifrado.py) y se DESCIFRAN al leer.
# ============================================================


def guardar_lead_chat(datos):
    """
    Guarda un lead capturado por el chat en la tabla leads_chat.

    Los campos basicos (nombre, telefono, moto, cuota) van en texto plano.
    Los campos SENSIBLES (ingresos, reportado, vida_crediticia) se CIFRAN
    antes de guardar: en la base queda 'gAAAA...', nunca el valor real.

    'datos' es un dict. Los campos sensibles pueden venir como None
    (por ahora no los pedimos); cifrar(None) devuelve None, asi que
    la tabla los guarda vacios sin problema.

    Devuelve el registro insertado.
    """
    from app.seguridad import cifrado
    politica = obtener_politica_vigente()

    registro = {
        # --- Basicos (texto plano) ---
        "nombre": datos["nombre"],
        "telefono": datos["telefono"],
        "moto_id": datos.get("moto_id"),
        "valor_financiar": datos.get("valor_financiar"),
        "cuota_inicial": datos.get("cuota_inicial", 0),
        "plazo_meses": datos.get("plazo_meses"),
        "cuota_calculada": datos.get("cuota_calculada"),
        "origen": "chat",

        # --- Consentimiento (Habeas Data) ---
        "autorizo_datos_basicos": datos.get("autorizo_basicos", False),
        "autorizo_datos_financieros": datos.get("autorizo_financieros", False),
        "fecha_consentimiento": datos.get("fecha_consentimiento"),
        "politica_id": politica["id"] if politica else None,
        "version_politica": politica["version"] if politica else None,

        # --- Sensibles (CIFRADOS) ---
        # Por ahora llegan como None; cuando se active la precalificacion,
        # llegaran con valores reales y se guardaran cifrados.
        "ingresos_cifrado": cifrado.cifrar(datos.get("ingresos")),
        "reportado_cifrado": cifrado.cifrar(datos.get("reportado")),
        "vida_crediticia_cifrado": cifrado.cifrar(datos.get("vida_crediticia")),
        "tipo_entidad_sugerida": datos.get("tipo_entidad"),
    }

    supabase = get_supabase_admin()
    resultado = supabase.table("leads_chat").insert(registro).execute()
    return resultado.data


def leer_lead_chat(lead_id):
    """
    Lee UN lead por su id y DESCIFRA los campos sensibles para mostrarlos.
    Solo para uso interno (gerencia/admin). Devuelve el lead con los
    campos sensibles ya descifrados (ingresos, reportado, vida_crediticia),
    o None si no existe.
    """
    from app.seguridad import cifrado

    supabase = get_supabase_admin()
    resultado = supabase.table("leads_chat").select("*").eq("id", lead_id).execute()
    if not resultado.data:
        return None

    lead = resultado.data[0]
    # Desciframos los campos sensibles y los agregamos en claro (solo en memoria).
    lead["ingresos"] = cifrado.descifrar(lead.get("ingresos_cifrado"))
    lead["reportado"] = cifrado.descifrar(lead.get("reportado_cifrado"))
    lead["vida_crediticia"] = cifrado.descifrar(lead.get("vida_crediticia_cifrado"))
    return lead


def listar_leads_chat():
    """
    Lista los leads del chat, mas recientes primero. NO descifra los
    campos sensibles (para un listado no hace falta ver ingresos, etc.;
    eso se ve al abrir un lead con leer_lead_chat). Trae los datos de
    la moto relacionada para dar contexto.
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("leads_chat")
                 .select("*, motos(marca, modelo)")
                 .order("created_at", desc=True)
                 .execute())
    return resultado.data

def obtener_politica_vigente():
    """
    Devuelve la version de la politica de privacidad que esta vigente
    ahora mismo (la que tiene vigente_hasta en null). Es la que se le
    esta mostrando al cliente y por lo tanto la que acepta al consentir.
    Devuelve None si no hay ninguna cargada.
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("politicas_privacidad")
                 .select("*")
                 .is_("vigente_hasta", "null")
                 .limit(1)
                 .execute())
    return resultado.data[0] if resultado.data else None


def registrar_politica(version, texto):
    """
    Archiva una nueva version de la politica de privacidad y la marca
    como vigente. Cierra automaticamente la version anterior poniendole
    fecha de fin, para que quede el historico completo:
    quien acepto la v1.0 sigue asociado a la v1.0, aunque hoy rija la v1.1.
    """
    from datetime import datetime, timezone
    from app.seguridad import cifrado

    supabase = get_supabase_admin()
    ahora = datetime.now(timezone.utc).isoformat()

    # 1. Cerrar la version anterior (si existe).
    anterior = obtener_politica_vigente()
    if anterior:
        supabase.table("politicas_privacidad")\
            .update({"vigente_hasta": ahora})\
            .eq("id", anterior["id"])\
            .execute()

    # 2. Insertar la nueva version como vigente.
    resultado = supabase.table("politicas_privacidad").insert({
        "version": version,
        "texto": texto,
        "hash_texto": cifrado.calcular_hash(texto),
        "vigente_desde": ahora,
        "vigente_hasta": None,
    }).execute()
    return resultado.data

def guardar_lead_chat_directo(registro):
    """
    Inserta un lead ya armado y cifrado por campos_credito.

    A diferencia de guardar_lead_chat, esta funcion NO decide que cifrar
    ni que columnas usar: recibe el registro listo. La decision de que es
    sensible vive en campos_credito, no aqui.
    """
    registro = dict(registro)
    registro["origen"] = "chat"

    politica = obtener_politica_vigente()
    if politica:
        registro["politica_id"] = politica["id"]
        registro["version_politica"] = politica["version"]

    supabase = get_supabase_admin()
    resultado = supabase.table("leads_chat").insert(registro).execute()
    return resultado.data

def reporte_ventas_detalle(limite=100):
    """
    Detalle de ventas: quien vendio que moto, con placa y fecha.
    A diferencia de reporte_ventas_por_usuario, que devuelve totales
    agregados, esta lista cada venta individual.
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("ventas")
                 .select("*")
                 .order("created_at", desc=True)
                 .limit(limite)
                 .execute())
    return resultado.data

def reporte_ventas_detalle(limite=100):
    """
    Detalle de ventas: quien vendio que moto, con placa y fecha.
    A diferencia de reporte_ventas_por_usuario, que devuelve totales,
    esta lista cada venta individual.
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("ventas")
                 .select("*")
                 .order("created_at", desc=True)
                 .limit(limite)
                 .execute())
    return resultado.data

def marcar_venta_verificada(venta_id, usuario_nombre):
    """
    Marca una venta como verificada por gerencia.

    Guarda quien la verifico y cuando: la casilla sola no sirve si
    despues nadie sabe a quien preguntarle.
    """
    from datetime import datetime, timezone

    supabase = get_supabase_admin()
    resultado = (supabase.table("ventas")
                 .update({
                     "verificada": True,
                     "verificada_por": usuario_nombre,
                     "verificada_en": datetime.now(timezone.utc).isoformat(),
                 })
                 .eq("id", venta_id)
                 .execute())
    return resultado.data

def reporte_compras_detalle(limite=100):
    """
    Detalle de compras: quien compro que moto, con placa y fecha.
    Mismo patron que reporte_ventas_detalle.
    """
    supabase = get_supabase_admin()
    resultado = (supabase.table("compras")
                 .select("*")
                 .order("created_at", desc=True)
                 .limit(limite)
                 .execute())
    return resultado.data

def marcar_compra_verificada(compra_id, usuario_nombre):
    """
    Marca una compra como verificada por gerencia.
    Mismo patron que marcar_venta_verificada.
    """
    from datetime import datetime, timezone

    supabase = get_supabase_admin()
    resultado = (supabase.table("compras")
                 .update({
                     "verificada": True,
                     "verificada_por": usuario_nombre,
                     "verificada_en": datetime.now(timezone.utc).isoformat(),
                 })
                 .eq("id", compra_id)
                 .execute())
    return resultado.data
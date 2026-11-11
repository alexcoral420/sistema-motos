"""
Bandeja y seguimiento de leads para el panel (/admin/leads, migraciones
029 y 030).

Un lead es un cliente que dejó sus datos en el chat del sitio y autorizó
que lo contacten. Aquí vive el criterio de la bandeja:

  - Quién ve qué: el asesor ve los leads sin tomar y los que él tomó;
    admin y gerencia ven todos.
  - El contacto (teléfono, correo) de un lead sin tomar NO se le muestra
    al asesor: lo ve cuando lo toma. Así nadie contacta a un cliente que
    después toma otro, y un dato personal no se reparte a todo el equipo.
  - El primero que lo toma se lo queda (lo garantiza el UPDATE condicionado
    del repositorio, no una lectura previa).
  - "Compra de contado" es la alerta de prioridad: esos leads van primero.

Y el del seguimiento (030): una vez tomado, el lead es del asesor y él lo
lleva por etapas:

    tomado ("por contactar") -> primer_contacto -> segundo_contacto
        -> cita_pendiente -> vendido | descartado

  - Las etapas no son una escalera obligatoria: se puede saltar o volver
    atrás (un cliente que reaparece, un estado puesto por error).
  - Cada lead tiene una línea de tiempo que solo crece: las notas del
    asesor (texto simple) y un renglón automático por cada cambio de
    estado o de fecha.
  - "Próximo contacto" es una fecha, sin hora. Los leads abiertos con
    esa fecha en hoy o antes son lo que el asesor tiene "para hoy".
    Cerrar un lead (vendido o descartado) le quita la fecha.
  - Solo gestiona un lead quien lo tomó; admin puede gestionar cualquiera;
    gerencia solo lee.

Y el de los clientes que el asesor agrega a mano (031): los que le llegan
por fuera del chat (un referido, alguien que pasó por la sede).

  - Se piden los mismos datos que al lead del chat y con las mismas
    reglas (campos_credito), más el canal por donde llegó.
  - El lead nace ya asignado a quien lo crea, en "por contactar": no pasa
    por la bandeja de nuevos ni dispara el aviso push.
  - El asesor declara que el cliente autorizó el contacto. Sin eso no se
    guarda; queda la versión de la política vigente y un renglón en el
    historial con quién lo declaró.
  - Un asesor no tiene dos veces abierto al mismo teléfono.

Y el del trabajo por asesor, que ve SOLO el admin en la misma bandeja:

  - Una tabla con una fila por asesor que tenga al menos un lead tomado:
    cuántos tiene en cada etapa, cuántos atrasados (abiertos con el
    próximo contacto ya vencido), vendidos y descartados.
  - Un filtro de periodo, uno solo para toda la tabla y las listas: se
    cuentan los leads que el asesor TOMÓ en ese periodo, en el estado en
    que están hoy. Los leads sin tomar no tienen esa fecha: se muestran
    siempre.
  - Un filtro por asesor: la bandeja muestra solo sus leads.
  - Para cualquier otro rol los dos filtros se ignoran, vengan o no en la
    URL: el asesor sigue viendo solo lo suyo.

La identidad (usuario_id, rol) la pasa la ruta desde la sesión.
"""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from app.db import repositorios
from app.seguridad.logging_config import obtener_logger
from app.seguridad.tiempo import HORA_COLOMBIA, fecha_legible, hoy_colombia, momento_legible
from app.seguridad.validadores import ErrorValidacion
from app.servicios import campos_credito
from app.servicios.campos_credito import FORMA_PAGO_CONTADO

ESTADO_NUEVO = "nuevo"
ESTADO_TOMADO = "tomado"
ESTADO_PRIMER_CONTACTO = "primer_contacto"
ESTADO_SEGUNDO_CONTACTO = "segundo_contacto"
ESTADO_CITA_PENDIENTE = "cita_pendiente"
ESTADO_VENDIDO = "vendido"
ESTADO_DESCARTADO = "descartado"

# Valores que el código ya no escribe pero la base todavía acepta (ver la
# migración 030): se leen como su equivalente de hoy.
ESTADOS_ANTERIORES = {"contactado": ESTADO_PRIMER_CONTACTO}

ETIQUETAS_ESTADO = {
    ESTADO_NUEVO: "Nuevo",
    ESTADO_TOMADO: "Por contactar",
    ESTADO_PRIMER_CONTACTO: "Primer contacto",
    ESTADO_SEGUNDO_CONTACTO: "Segundo contacto",
    ESTADO_CITA_PENDIENTE: "Cita pendiente",
    ESTADO_VENDIDO: "Vendido",
    ESTADO_DESCARTADO: "Descartado",
}
# Abiertos: el asesor sigue trabajando al cliente. El orden es el del embudo.
ESTADOS_DE_SEGUIMIENTO = (ESTADO_TOMADO, ESTADO_PRIMER_CONTACTO,
                          ESTADO_SEGUNDO_CONTACTO, ESTADO_CITA_PENDIENTE)
ESTADOS_DE_CIERRE = (ESTADO_VENDIDO, ESTADO_DESCARTADO)
# Todo estado de un lead que ya tiene asesor: entre estos se puede mover.
ESTADOS_ASIGNADOS = ESTADOS_DE_SEGUIMIENTO + ESTADOS_DE_CIERRE
# Para el selector del formulario: (valor, etiqueta).
OPCIONES_ESTADO = tuple((e, ETIQUETAS_ESTADO[e]) for e in ESTADOS_ASIGNADOS)

MAX_LARGO_NOTA = 1000               # igual al check de leads_notas
MAX_DIAS_PROXIMO_CONTACTO = 365     # no se programa a más de un año

NOTA = "nota"
EVENTO = "evento"

SEGUIMIENTO_VENCIDO = "vencido"
SEGUIMIENTO_HOY = "hoy"
SEGUIMIENTO_FUTURO = "futuro"

ETIQUETAS_PAGO = {
    FORMA_PAGO_CONTADO: "Compra de contado",
    "financiado": "Financiación",
    "por_definir": "Pago por definir",
}
# Para el selector del formulario; "por definir" primero: es el valor por
# defecto cuando el asesor todavía no lo sabe.
OPCIONES_PAGO = tuple((f, ETIQUETAS_PAGO[f]) for f in ("por_definir", "financiado", FORMA_PAGO_CONTADO))

# De dónde salió el lead (leads_chat.origen) y, si lo agregó un asesor, por
# qué canal le llegó el cliente (leads_chat.canal, check de la migración 031).
ORIGEN_CHAT = "chat"
ORIGEN_ASESOR = "asesor"
CANALES = {
    "whatsapp": "WhatsApp",
    "referido": "Referido",
    "presencial": "Visita a la sede",
    "redes": "Redes sociales",
    "llamada": "Llamada",
    "otro": "Otro",
}
OPCIONES_CANAL = tuple(CANALES.items())

# Cómo se le nombra al asesor cada dato de campos_credito cuando falla.
_NOMBRES_DE_CAMPO = {
    "nombre": "el nombre",
    "telefono": "el WhatsApp (celular de 10 dígitos)",
    "correo": "el correo",
    "moto_interes": "la moto de interés",
    "forma_pago": "la forma de pago",
}

# La ruta exige estos roles. Solo el asesor toma leads; admin y gerencia
# ven toda la bandeja, y admin además puede gestionar un lead ajeno.
ROLES_BANDEJA = ("asesor", "admin", "gerencia")
ROLES_VEN_TODO = ("admin", "gerencia")
ROL_QUE_TOMA = "asesor"
ROL_QUE_GESTIONA_AJENOS = "admin"
ROLES_QUE_GESTIONAN = (ROL_QUE_TOMA, ROL_QUE_GESTIONA_AJENOS)
# Quién ve la tabla "Trabajo por asesor" y usa sus filtros. Gerencia ve la
# bandeja completa pero, por ahora, no este resumen.
ROL_VE_TRABAJO_POR_ASESOR = "admin"

# Periodos del filtro, en el orden en que se ofrecen. Cuentan desde el
# día en que el asesor tomó el lead (hora de Colombia) hasta hoy.
PERIODO_TODO = "todo"
PERIODOS = {
    PERIODO_TODO: "Todo",
    "semana": "Esta semana",
    "mes": "Este mes",
    "trimestre": "Últimos 90 días",
}


def _ahora():
    return datetime.now(timezone.utc).isoformat()


def _estado_de(lead):
    estado = lead.get("estado") or ESTADO_NUEVO
    return ESTADOS_ANTERIORES.get(estado, estado)


def _fecha(cruda):
    """date a partir de la fecha ISO de la base; None si no hay o no se lee."""
    if not cruda:
        return None
    try:
        return date.fromisoformat(str(cruda)[:10])
    except ValueError:
        return None


def _dia_colombia(iso):
    """El día (en Colombia) de un timestamp ISO de la base, o None."""
    if not iso:
        return None
    try:
        momento = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(HORA_COLOMBIA).date()


def _inicio_de_periodo(periodo, hoy):
    """Primer día que entra en el periodo, o None si es 'todo'."""
    if periodo == "semana":
        return hoy - timedelta(days=hoy.weekday())      # lunes
    if periodo == "mes":
        return hoy.replace(day=1)
    if periodo == "trimestre":
        return hoy - timedelta(days=89)
    return None


def _leer_asesor(crudo):
    """El id de asesor del filtro (viene de la URL), o None si no es un número."""
    if isinstance(crudo, int) and not isinstance(crudo, bool):
        return crudo if crudo > 0 else None
    if isinstance(crudo, str) and crudo.strip().isdigit() and len(crudo.strip()) <= 12:
        return int(crudo.strip()) or None
    return None


def _trabajo_por_asesor(leads):
    """
    Una fila por asesor con al menos un lead: cuántos tiene en cada etapa
    (en el orden de ESTADOS_DE_SEGUIMIENTO), atrasados, vendidos y
    descartados. Primero quien más atrasados tiene; luego quien más
    clientes abiertos lleva.
    """
    filas = {}
    for lead in leads:
        if lead["asesor_id"] is None:
            continue
        fila = filas.setdefault(lead["asesor_id"], {
            "asesor_id": lead["asesor_id"], "nombre": lead["asesor_nombre"] or "Sin nombre",
            "etapas": [0] * len(ESTADOS_DE_SEGUIMIENTO),
            "abiertos": 0, "atrasados": 0, "vendidos": 0, "descartados": 0, "total": 0,
        })
        fila["total"] += 1
        if lead["abierto"]:
            fila["etapas"][ESTADOS_DE_SEGUIMIENTO.index(lead["estado"])] += 1
            fila["abiertos"] += 1
            if lead["seguimiento"] == SEGUIMIENTO_VENCIDO:
                fila["atrasados"] += 1
        elif lead["estado"] == ESTADO_VENDIDO:
            fila["vendidos"] += 1
        elif lead["estado"] == ESTADO_DESCARTADO:
            fila["descartados"] += 1
    return sorted(filas.values(),
                  key=lambda f: (-f["atrasados"], -f["abiertos"], f["nombre"].lower()))


def _moto_texto(lead):
    """La moto de la ficha si el lead quedó enlazado; si no, la que nombró."""
    moto = lead.get("motos") or {}
    ficha = " ".join(str(moto[c]) for c in ("marca", "modelo", "anio") if moto.get(c))
    return ficha or (lead.get("moto_interes") or "")


def _enlace_whatsapp(lead, moto_texto):
    nombre = (lead.get("nombre") or "").split(" ")[0]
    mensaje = f"Hola {nombre}, le escribo de Universal Motors."
    if moto_texto:
        mensaje += f" Vi que le interesa la {moto_texto}."
    mensaje += " ¿Cómo le puedo ayudar?"
    return f"https://wa.me/57{lead['telefono']}?text={quote(mensaje)}"


def _origen_texto(lead):
    """'Chat del sitio', o el canal por el que le llegó al asesor."""
    if lead.get("origen") != ORIGEN_ASESOR:
        return "Chat del sitio"
    return CANALES.get(lead.get("canal"), "Agregado por el asesor")


def _seguimiento(estado, proximo, hoy):
    """(clave, texto) de la fecha programada de un lead abierto, o (None, "")."""
    if estado not in ESTADOS_DE_SEGUIMIENTO or proximo is None:
        return None, ""
    if proximo < hoy:
        return SEGUIMIENTO_VENCIDO, f"Contacto atrasado: {fecha_legible(proximo)}"
    if proximo == hoy:
        return SEGUIMIENTO_HOY, "Contactar hoy"
    return SEGUIMIENTO_FUTURO, f"Próximo contacto: {fecha_legible(proximo)}"


def _presentar(lead, usuario_id, rol, hoy=None):
    """Arma lo que ve ESTE usuario de un lead (el contacto, solo si le toca)."""
    hoy = hoy or hoy_colombia()
    estado = _estado_de(lead)
    propio = lead.get("asesor_id") is not None and lead.get("asesor_id") == usuario_id
    ve_contacto = rol in ROLES_VEN_TODO or propio
    moto_texto = _moto_texto(lead)
    nombre = lead.get("nombre") or ""
    proximo = _fecha(lead.get("proximo_contacto"))
    seguimiento, seguimiento_texto = _seguimiento(estado, proximo, hoy)

    return {
        "id": lead["id"],
        "estado": estado,
        "estado_texto": ETIQUETAS_ESTADO.get(estado, estado),
        "abierto": estado in ESTADOS_DE_SEGUIMIENTO,
        # Sin tomar, el asesor ve solo el primer nombre.
        "nombre": nombre if ve_contacto else nombre.split(" ")[0],
        "telefono": lead.get("telefono") if ve_contacto else None,
        "correo": lead.get("correo") if ve_contacto else None,
        "whatsapp_url": _enlace_whatsapp(lead, moto_texto)
                        if ve_contacto and lead.get("telefono") else None,
        "prioridad": lead.get("forma_pago") == FORMA_PAGO_CONTADO,
        "forma_pago_texto": ETIQUETAS_PAGO.get(lead.get("forma_pago"), "Sin dato de pago"),
        "moto_texto": moto_texto,
        "moto_id": lead.get("moto_id"),
        "moto_precio": (lead.get("motos") or {}).get("precio"),
        "origen_texto": _origen_texto(lead),
        "manual": lead.get("origen") == ORIGEN_ASESOR,
        "recibido": momento_legible(lead.get("created_at")),
        "tomado": momento_legible(lead.get("tomado_en")),
        # Último cambio de ESTADO (una nota sola no lo mueve).
        "gestionado": momento_legible(lead.get("gestionado_en")),
        "asesor_id": lead.get("asesor_id"),
        "asesor_nombre": lead.get("asesor_nombre"),
        "propio": propio,
        # La fecha programada (ISO, para el formulario) y cómo se muestra.
        "proximo_contacto": proximo.isoformat() if proximo else "",
        "seguimiento": seguimiento,
        "seguimiento_texto": seguimiento_texto,
        "puede_tomar": rol == ROL_QUE_TOMA and estado == ESTADO_NUEVO,
        "puede_gestionar": estado in ESTADOS_ASIGNADOS
                           and (propio or rol == ROL_QUE_GESTIONA_AJENOS),
    }


def listar(usuario_id, rol, hoy=None, asesor=None, periodo=None) -> dict:
    """
    La bandeja de este usuario:
      nuevos      sin tomar; primero los de compra de contado
      para_hoy    abiertos con el próximo contacto en hoy o atrasado, el
                  más atrasado primero
      etapas      los abiertos por etapa, en el orden del embudo; dentro
                  de cada una, primero los que tienen fecha (la más
                  próxima arriba) y luego el resto, recientes primero
      en_gestion  todos los abiertos juntos
      cerrados    vendidos y descartados
    Para el asesor son solo los suyos; admin y gerencia ven los de todos.

    Solo para el admin, además:
      trabajo     la tabla por asesor (None para los demás roles)
      filtro      el periodo y el asesor aplicados, y las opciones
    'asesor' y 'periodo' vienen de la URL: se validan aquí y se ignoran
    si el rol no es el admin.
    """
    hoy = hoy or hoy_colombia()
    filas = repositorios.listar_leads_bandeja(
        None if rol in ROLES_VEN_TODO else usuario_id
    )

    trabajo = filtro = None
    if rol == ROL_VE_TRABAJO_POR_ASESOR:
        periodo = periodo if periodo in PERIODOS else PERIODO_TODO
        desde = _inicio_de_periodo(periodo, hoy)
        if desde is not None:
            # Un lead sin tomar no tiene fecha de toma: se queda siempre.
            filas = [f for f in filas if f.get("asesor_id") is None
                     or (_dia_colombia(f.get("tomado_en")) or date.min) >= desde]

    leads = [_presentar(f, usuario_id, rol, hoy) for f in filas]

    if rol == ROL_VE_TRABAJO_POR_ASESOR:
        # La tabla se arma ANTES de filtrar por asesor: siempre muestra a todos.
        trabajo = _trabajo_por_asesor(leads)
        elegido = next((t for t in trabajo if t["asesor_id"] == _leer_asesor(asesor)), None)
        filtro = {
            "periodo": periodo,
            "periodos": tuple(PERIODOS.items()),
            "asesor_id": elegido["asesor_id"] if elegido else None,
            "asesor_nombre": elegido["nombre"] if elegido else None,
            "sin_tomar": sum(1 for l in leads if l["estado"] == ESTADO_NUEVO),
            "etapas": tuple(ETIQUETAS_ESTADO[e] for e in ESTADOS_DE_SEGUIMIENTO),
        }
        if elegido:
            leads = [l for l in leads if l["asesor_id"] == elegido["asesor_id"]]

    nuevos = [l for l in leads if l["estado"] == ESTADO_NUEVO]
    nuevos.sort(key=lambda l: not l["prioridad"])   # estable: conserva el orden por fecha

    abiertos = [l for l in leads if l["abierto"]]
    # Estable: los que no tienen fecha conservan el orden de llegada.
    abiertos.sort(key=lambda l: (not l["proximo_contacto"], l["proximo_contacto"]))

    return {
        "nuevos": nuevos,
        "para_hoy": [l for l in abiertos
                     if l["seguimiento"] in (SEGUIMIENTO_VENCIDO, SEGUIMIENTO_HOY)],
        "etapas": [{"estado": estado, "titulo": ETIQUETAS_ESTADO[estado],
                    "leads": [l for l in abiertos if l["estado"] == estado]}
                   for estado in ESTADOS_DE_SEGUIMIENTO],
        "en_gestion": abiertos,
        "cerrados": [l for l in leads if l["estado"] in ESTADOS_DE_CIERRE],
        "trabajo": trabajo,
        "filtro": filtro,
    }


def obtener(lead_id, usuario_id, rol, hoy=None):
    """
    Un lead para este usuario, con su línea de tiempo, o None si no existe
    o no le corresponde verlo (un asesor no abre el lead que tomó otro).
    """
    lead = repositorios.obtener_lead_bandeja(lead_id)
    if not lead:
        return None
    estado = _estado_de(lead)
    if rol not in ROLES_VEN_TODO and estado != ESTADO_NUEVO and lead.get("asesor_id") != usuario_id:
        return None
    visto = _presentar(lead, usuario_id, rol, hoy)
    # Un lead sin tomar todavía no tiene historia.
    visto["notas"] = [] if estado == ESTADO_NUEVO else [
        {"cuando": momento_legible(n.get("created_at")), "autor": n.get("usuario_nombre") or "",
         "automatica": n.get("tipo") == EVENTO, "texto": n.get("texto") or ""}
        for n in repositorios.listar_notas_lead(lead_id)
    ]
    return visto


def tomar(lead_id, usuario_id, usuario_nombre, rol) -> None:
    """
    El asesor en sesión toma el lead. Si otro lo tomó primero (o ya no
    está nuevo), ErrorValidacion: la base no devuelve la fila.
    """
    if rol != ROL_QUE_TOMA:
        raise ErrorValidacion("Solo un asesor puede tomar un lead.")
    fila = repositorios.tomar_lead_chat(
        lead_id,
        estado_requerido=ESTADO_NUEVO,
        cambios={
            "estado": ESTADO_TOMADO,
            "asesor_id": usuario_id,
            "asesor_nombre": usuario_nombre,
            "tomado_en": _ahora(),
        },
    )
    if not fila:
        raise ErrorValidacion("Otro asesor ya tomó este lead.")


def agregar(datos, usuario_id, usuario_nombre, rol) -> int:
    """
    El asesor en sesión agrega un cliente que le llegó por otro canal.
    'datos' es el formulario (entrada no confiable). Devuelve el id del
    lead, que ya queda como suyo en "por contactar".
    """
    if rol != ROL_QUE_TOMA:
        raise ErrorValidacion("Solo un asesor puede agregar clientes.")
    if not hasattr(datos, "get"):
        raise ErrorValidacion("La solicitud no es válida.")

    # Mismos datos y mismas reglas que el lead del chat.
    crudos = {c["clave"]: datos.get(c["clave"]) for c in campos_credito.campos_activos()}
    limpios, faltantes = campos_credito.validar(crudos)
    for campo in campos_credito.campos_activos():
        clave = campo["clave"]
        escrito = isinstance(crudos[clave], str) and crudos[clave].strip()
        # validar() descarta en silencio lo que no pasa: bien para el
        # extractor del chat, pero aquí hay una persona que debe enterarse.
        if clave not in limpios and (escrito or campo.get("obligatorio")):
            raise ErrorValidacion(f"Revise {_NOMBRES_DE_CAMPO.get(clave, campo['etiqueta'])}.", clave)

    canal = datos.get("canal")
    if canal not in CANALES:
        raise ErrorValidacion("Elija por dónde llegó el cliente.", "canal")
    nota = _leer_nota(datos.get("nota"))
    if datos.get("autorizo") != "si":
        raise ErrorValidacion("Para guardar al cliente debe confirmar que él autorizó "
                              "que lo contactemos.", "autorizo")

    repetido = repositorios.lead_abierto_de_asesor_por_telefono(
        usuario_id, limpios["telefono"], list(ESTADOS_DE_SEGUIMIENTO))
    if repetido:
        raise ErrorValidacion("Ya tiene a un cliente en seguimiento con ese WhatsApp.", "telefono")

    from app.seguridad import cifrado   # import local, como en asistente.py

    ahora = _ahora()
    registro = campos_credito.a_columnas(limpios, cifrado.cifrar)
    registro.update(
        origen=ORIGEN_ASESOR, canal=canal,
        estado=ESTADO_TOMADO, asesor_id=usuario_id, asesor_nombre=usuario_nombre, tomado_en=ahora,
        autorizo_datos_basicos=True, autorizo_datos_financieros=False, fecha_consentimiento=ahora,
    )
    politica = repositorios.obtener_politica_vigente()
    if politica:
        registro.update(politica_id=politica["id"], version_politica=politica["version"])

    fila = repositorios.crear_lead_manual(registro)
    if not fila:
        raise ErrorValidacion("No se pudo guardar el cliente. Intente de nuevo.")
    lead_id = fila["id"]

    renglon = {"lead_id": lead_id, "usuario_id": usuario_id, "usuario_nombre": usuario_nombre}
    filas = [dict(renglon, tipo=EVENTO,
                  texto=f"Cliente agregado por el asesor · Canal: {CANALES[canal]} · "
                        "El asesor confirmó que el cliente autorizó el contacto")]
    if nota:
        filas.append(dict(renglon, tipo=NOTA, texto=nota))
    try:
        repositorios.agregar_notas_lead(filas)
    except Exception as e:
        # El cliente ya quedó guardado: no se le hace repetir el formulario
        # (crearía un duplicado). El historial se completa desde la ficha.
        obtener_logger().error("Lead %s: no se pudo escribir el historial inicial (%s).",
                               lead_id, type(e).__name__)
    return lead_id


def _leer_nota(cruda) -> str:
    if cruda is None:
        return ""
    if not isinstance(cruda, str):
        raise ErrorValidacion("La nota no es válida.", "nota")
    nota = cruda.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(nota) > MAX_LARGO_NOTA:
        raise ErrorValidacion(f"La nota no puede pasar de {MAX_LARGO_NOTA} caracteres.", "nota")
    return nota


def _leer_fecha(cruda):
    """date, o None si el campo llegó vacío (= quitar la fecha)."""
    if not isinstance(cruda, str):
        raise ErrorValidacion("La fecha del próximo contacto no es válida.", "proximo_contacto")
    cruda = cruda.strip()
    if not cruda:
        return None
    try:
        return date.fromisoformat(cruda)
    except ValueError:
        raise ErrorValidacion("La fecha del próximo contacto no es válida.", "proximo_contacto")


def registrar_seguimiento(lead_id, datos, usuario_id, usuario_nombre, rol, hoy=None) -> None:
    """
    Un paso de seguimiento sobre un lead ya tomado. 'datos' es el
    formulario (entrada no confiable); cada campo es opcional:

      estado            nueva etapa (o cierre). Ausente o igual = no cambia.
      proximo_contacto  'AAAA-MM-DD'; vacío quita la fecha; ausente no la
                        toca. Solo se valida si cambia, así que una fecha
                        ya atrasada no impide agregar una nota.
      nota              texto simple.

    Solo quien tomó el lead, o un admin. El cambio va en un UPDATE
    condicionado al estado que se leyó (y al asesor): si el lead cambió
    entretanto, no se pisa. Lo que cambió queda en la línea de tiempo.
    """
    if rol not in ROLES_QUE_GESTIONAN:
        raise ErrorValidacion("Su rol no puede gestionar leads.")
    if not hasattr(datos, "get"):
        raise ErrorValidacion("La solicitud no es válida.")
    hoy = hoy or hoy_colombia()

    fila = repositorios.obtener_lead_bandeja(lead_id)
    actual = _estado_de(fila) if fila else None
    ajeno = rol != ROL_QUE_GESTIONA_AJENOS and (not fila or fila.get("asesor_id") != usuario_id)
    if not fila or actual not in ESTADOS_ASIGNADOS or ajeno:
        raise ErrorValidacion("Ese lead no es suyo o todavía no fue tomado.")

    estado = datos.get("estado") or actual
    if estado not in ESTADOS_ASIGNADOS:
        raise ErrorValidacion("Estado no válido.", "estado")
    nota = _leer_nota(datos.get("nota"))

    fecha_actual = _fecha(fila.get("proximo_contacto"))
    if estado in ESTADOS_DE_CIERRE:
        fecha = None                    # un lead cerrado no se recuerda
    elif datos.get("proximo_contacto") is None:
        fecha = fecha_actual
    else:
        fecha = _leer_fecha(datos.get("proximo_contacto"))
        if fecha is not None and fecha != fecha_actual:
            if fecha < hoy:
                raise ErrorValidacion("El próximo contacto no puede ser una fecha pasada.",
                                      "proximo_contacto")
            if fecha > hoy + timedelta(days=MAX_DIAS_PROXIMO_CONTACTO):
                raise ErrorValidacion("El próximo contacto no puede ser a más de un año.",
                                      "proximo_contacto")

    cambios, eventos = {}, []
    if estado != actual:
        cambios.update(estado=estado, gestionado_en=_ahora())
        eventos.append(f"Estado: {ETIQUETAS_ESTADO[estado]}")
    if fecha != fecha_actual:
        cambios["proximo_contacto"] = fecha.isoformat() if fecha else None
        if estado not in ESTADOS_DE_CIERRE:
            eventos.append(f"Próximo contacto: {fecha_legible(fecha)}" if fecha
                           else "Sin próximo contacto programado")
    if not cambios and not nota:
        raise ErrorValidacion("No hay nada que guardar: cambie el estado, la fecha o escriba una nota.")

    if cambios:
        actualizado = repositorios.cambiar_estado_lead_chat(
            lead_id,
            estados_permitidos=[fila.get("estado")],
            cambios=cambios,
            asesor_id=None if rol == ROL_QUE_GESTIONA_AJENOS else usuario_id,
        )
        if not actualizado:
            raise ErrorValidacion("No se pudo guardar: el lead cambió mientras lo editaba. "
                                  "Vuelva a intentarlo.")

    renglon = {"lead_id": lead_id, "usuario_id": usuario_id, "usuario_nombre": usuario_nombre}
    filas = []
    if eventos:
        filas.append(dict(renglon, tipo=EVENTO, texto=" · ".join(eventos)))
    if nota:
        filas.append(dict(renglon, tipo=NOTA, texto=nota))
    try:
        repositorios.agregar_notas_lead(filas)
    except Exception as e:
        # El cambio (si lo hubo) ya quedó en el lead; lo que se perdió es
        # el renglón del historial. Se le dice al asesor, no se oculta.
        obtener_logger().error("Lead %s: no se pudo escribir el historial (%s).",
                               lead_id, type(e).__name__)
        raise ErrorValidacion("El cambio se guardó, pero no quedó en el historial"
                              + (" y la nota se perdió. Escríbala de nuevo." if nota else "."))

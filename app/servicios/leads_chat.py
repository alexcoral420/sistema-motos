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

La identidad (usuario_id, rol) la pasa la ruta desde la sesión.
"""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from app.db import repositorios
from app.seguridad.logging_config import obtener_logger
from app.seguridad.tiempo import fecha_legible, hoy_colombia, momento_legible
from app.seguridad.validadores import ErrorValidacion
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

# La ruta exige estos roles. Solo el asesor toma leads; admin y gerencia
# ven toda la bandeja, y admin además puede gestionar un lead ajeno.
ROLES_BANDEJA = ("asesor", "admin", "gerencia")
ROLES_VEN_TODO = ("admin", "gerencia")
ROL_QUE_TOMA = "asesor"
ROL_QUE_GESTIONA_AJENOS = "admin"
ROLES_QUE_GESTIONAN = (ROL_QUE_TOMA, ROL_QUE_GESTIONA_AJENOS)


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
        "recibido": momento_legible(lead.get("created_at")),
        "tomado": momento_legible(lead.get("tomado_en")),
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


def listar(usuario_id, rol, hoy=None) -> dict:
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
    """
    hoy = hoy or hoy_colombia()
    filas = repositorios.listar_leads_bandeja(
        None if rol in ROLES_VEN_TODO else usuario_id
    )
    leads = [_presentar(f, usuario_id, rol, hoy) for f in filas]

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

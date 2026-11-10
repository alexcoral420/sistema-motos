"""
Bandeja de leads del chat para el panel (/admin/leads, migración 029).

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

La identidad (usuario_id, rol) la pasa la ruta desde la sesión.
"""

from datetime import datetime, timezone
from urllib.parse import quote

from app.db import repositorios
from app.seguridad.tiempo import momento_legible
from app.seguridad.validadores import ErrorValidacion
from app.servicios.campos_credito import FORMA_PAGO_CONTADO

ESTADO_NUEVO = "nuevo"
ESTADO_TOMADO = "tomado"
ESTADO_CONTACTADO = "contactado"
ESTADO_DESCARTADO = "descartado"

ETIQUETAS_ESTADO = {
    ESTADO_NUEVO: "Nuevo",
    ESTADO_TOMADO: "Tomado",
    ESTADO_CONTACTADO: "Contactado",
    ESTADO_DESCARTADO: "Descartado",
}
# A qué puede pasar un lead ya tomado, y desde dónde.
ESTADOS_DE_CIERRE = (ESTADO_CONTACTADO, ESTADO_DESCARTADO)
ESTADOS_EN_GESTION = (ESTADO_TOMADO, ESTADO_CONTACTADO, ESTADO_DESCARTADO)

ETIQUETAS_PAGO = {
    FORMA_PAGO_CONTADO: "Compra de contado",
    "financiado": "Financiación",
    "por_definir": "Pago por definir",
}

# La ruta exige estos roles. Solo el asesor toma leads; admin y gerencia
# ven toda la bandeja, y admin además puede cerrar un lead ajeno.
ROLES_BANDEJA = ("asesor", "admin", "gerencia")
ROLES_VEN_TODO = ("admin", "gerencia")
ROL_QUE_TOMA = "asesor"
ROL_QUE_CIERRA_AJENOS = "admin"


def _ahora():
    return datetime.now(timezone.utc).isoformat()


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


def _presentar(lead, usuario_id, rol):
    """Arma lo que ve ESTE usuario de un lead (el contacto, solo si le toca)."""
    estado = lead.get("estado") or ESTADO_NUEVO
    propio = lead.get("asesor_id") is not None and lead.get("asesor_id") == usuario_id
    ve_contacto = rol in ROLES_VEN_TODO or propio
    moto_texto = _moto_texto(lead)
    nombre = lead.get("nombre") or ""

    return {
        "id": lead["id"],
        "estado": estado,
        "estado_texto": ETIQUETAS_ESTADO.get(estado, estado),
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
        "puede_tomar": rol == ROL_QUE_TOMA and estado == ESTADO_NUEVO,
        "puede_cerrar": estado in (ESTADO_TOMADO, ESTADO_CONTACTADO)
                        and (propio or rol == ROL_QUE_CIERRA_AJENOS),
    }


def listar(usuario_id, rol) -> dict:
    """
    La bandeja de este usuario, en tres grupos:
      nuevos      sin tomar; primero los de compra de contado
      en_gestion  tomados (del asesor, o de todos para admin/gerencia)
      cerrados    contactados y descartados
    Dentro de cada grupo, los más recientes primero.
    """
    filas = repositorios.listar_leads_bandeja(
        None if rol in ROLES_VEN_TODO else usuario_id
    )
    leads = [_presentar(f, usuario_id, rol) for f in filas]

    nuevos = [l for l in leads if l["estado"] == ESTADO_NUEVO]
    nuevos.sort(key=lambda l: not l["prioridad"])   # estable: conserva el orden por fecha

    return {
        "nuevos": nuevos,
        "en_gestion": [l for l in leads if l["estado"] == ESTADO_TOMADO],
        "cerrados": [l for l in leads if l["estado"] in ESTADOS_DE_CIERRE],
    }


def obtener(lead_id, usuario_id, rol):
    """
    Un lead para este usuario, o None si no existe o no le corresponde
    verlo (un asesor no abre el lead que ya tomó otro).
    """
    lead = repositorios.obtener_lead_bandeja(lead_id)
    if not lead:
        return None
    estado = lead.get("estado") or ESTADO_NUEVO
    if rol not in ROLES_VEN_TODO and estado != ESTADO_NUEVO and lead.get("asesor_id") != usuario_id:
        return None
    return _presentar(lead, usuario_id, rol)


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


def cerrar(lead_id, estado, usuario_id, rol) -> None:
    """
    Marca un lead tomado como contactado o descartado. Solo quien lo
    tomó (o un admin). Se puede corregir entre los dos estados de cierre.
    """
    if estado not in ESTADOS_DE_CIERRE:
        raise ErrorValidacion("Estado no válido.")
    if rol not in (ROL_QUE_TOMA, ROL_QUE_CIERRA_AJENOS):
        raise ErrorValidacion("Su rol no puede gestionar leads.")
    fila = repositorios.cambiar_estado_lead_chat(
        lead_id,
        estados_permitidos=list(ESTADOS_EN_GESTION),
        cambios={"estado": estado, "gestionado_en": _ahora()},
        asesor_id=None if rol == ROL_QUE_CIERRA_AJENOS else usuario_id,
    )
    if not fila:
        raise ErrorValidacion("No se pudo actualizar: el lead no es suyo o todavía no fue tomado.")

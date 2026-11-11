"""
"Mi espacio" del asesor en el panel (/admin/mi-espacio).

La página de llegada del asesor: cuántas ventas, compras y permutas hizo
en la semana (lunes a domingo), el detalle de cada una y los leads del
chat disponibles para contactar. Arriba de todo, sus clientes en
seguimiento que tocan hoy (o están atrasados) y los que tomó y todavía
no contacta: es lo primero que tiene que ver al entrar.

Criterios:
  - Solo lo del asesor en sesión: se filtra por asesor_id (quién hizo el
    negocio), no por quién lo registró. El id lo pasa la ruta desde la
    sesión, nunca la URL.
  - SIN VALORES EN PESOS: el asesor ve conteos y qué moto fue, no
    precios. Las consultas del repositorio ni siquiera traen esas columnas.
  - Las ventas anuladas no cuentan (mismo criterio que el resumen de
    gerencia: solo estado 'activa').
  - La semana se corta en hora de Colombia, no en UTC: una venta del
    domingo a las 8 p. m. es de esa semana.
"""

from datetime import date, datetime, time, timedelta

from app.db import repositorios
from app.seguridad.tiempo import HORA_COLOMBIA, MESES, hoy_colombia, momento_legible
from app.servicios import leads_chat

ROL_ESPACIO = "asesor"
ESTADO_VENTA_VALIDA = "activa"
LEADS_EN_PORTADA = 5


def semana_de(cruda=None, hoy=None):
    """
    (lunes, domingo) de la semana pedida. 'cruda' viene de la URL
    ('AAAA-MM-DD', cualquier día de esa semana): si falta, no es una
    fecha o cae en el futuro, se usa la semana actual.
    """
    hoy = hoy or hoy_colombia()
    dia = hoy
    if isinstance(cruda, str):
        try:
            pedida = date.fromisoformat(cruda.strip())
            if pedida <= hoy:
                dia = pedida
        except ValueError:
            pass
    lunes = dia - timedelta(days=dia.weekday())
    return lunes, lunes + timedelta(days=6)


def _periodo(lunes, domingo):
    """'Del 9 al 15 de noviembre de 2026' (o con los dos meses si cambia)."""
    if lunes.month == domingo.month:
        return f"Del {lunes.day} al {domingo.day} de {MESES[domingo.month - 1]} de {domingo.year}"
    return (f"Del {lunes.day} de {MESES[lunes.month - 1]} "
            f"al {domingo.day} de {MESES[domingo.month - 1]} de {domingo.year}")


def resumen(usuario_id, semana_cruda=None, hoy=None) -> dict:
    """
    Todo lo que muestra la portada del asesor para una semana:
    periodo y navegación entre semanas, ventas/compras/permutas (cantidad
    y filas, sin precios) y sus leads del chat.
    """
    hoy = hoy or hoy_colombia()
    lunes, domingo = semana_de(semana_cruda, hoy)
    lunes_actual, _ = semana_de(None, hoy)

    inicio = datetime.combine(lunes, time.min, tzinfo=HORA_COLOMBIA).isoformat()
    fin = datetime.combine(domingo + timedelta(days=1), time.min, tzinfo=HORA_COLOMBIA).isoformat()

    ventas = [
        {"cuando": momento_legible(v.get("created_at")), "moto": v.get("descripcion") or "",
         "placa": v.get("placa"), "verificada": bool(v.get("verificada"))}
        for v in repositorios.ventas_de_asesor_en_rango(usuario_id, inicio, fin)
        if v.get("estado") == ESTADO_VENTA_VALIDA
    ]
    compras = [
        {"cuando": momento_legible(c.get("created_at")), "moto": c.get("descripcion") or "",
         "placa": c.get("placa"), "verificada": bool(c.get("verificada"))}
        for c in repositorios.compras_de_asesor_en_rango(usuario_id, inicio, fin)
    ]
    permutas = [
        {"cuando": momento_legible(p.get("created_at")),
         "entrante": p.get("descripcion_entrante") or "",
         "saliente": p.get("descripcion_saliente") or ""}
        for p in repositorios.permutas_de_asesor_en_rango(usuario_id, inicio, fin)
    ]

    leads = leads_chat.listar(usuario_id, ROL_ESPACIO, hoy)
    para_hoy = leads["para_hoy"]
    # Tomados y sin primer contacto. Los que ya salen en "para hoy" no se repiten.
    ya_listados = {l["id"] for l in para_hoy}
    por_contactar = [l for l in leads["etapas"][0]["leads"] if l["id"] not in ya_listados]

    return {
        "periodo": _periodo(lunes, domingo),
        "es_semana_actual": lunes == lunes_actual,
        "semana_anterior": (lunes - timedelta(days=7)).isoformat(),
        # No se navega al futuro.
        "semana_siguiente": None if lunes >= lunes_actual
                            else (lunes + timedelta(days=7)).isoformat(),
        "ventas": ventas,
        "compras": compras,
        "permutas": permutas,
        "leads_para_hoy": para_hoy,
        "leads_por_contactar": por_contactar[:LEADS_EN_PORTADA],
        "total_leads_por_contactar": len(por_contactar),
        "leads_nuevos": leads["nuevos"][:LEADS_EN_PORTADA],
        "total_leads_nuevos": len(leads["nuevos"]),
        "total_leads_en_gestion": len(leads["en_gestion"]),
    }

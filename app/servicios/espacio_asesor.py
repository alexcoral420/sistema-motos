"""
"Mi espacio" del asesor en el panel (/admin/mi-espacio).

La página de llegada del asesor: cuántas ventas, compras y permutas hizo
en la semana (lunes a domingo), el detalle de cada una y los leads del
chat disponibles para contactar. Arriba de todo, sus clientes: los que
tocan hoy (o están atrasados) y, debajo, todos los que tiene en
seguimiento agrupados por etapa. Es lo primero que tiene que ver al
entrar: un lead que tomó no puede desaparecer de su portada.

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
LEADS_EN_PORTADA = 5       # leads disponibles que se listan
CLIENTES_POR_ETAPA = 5     # clientes en seguimiento que se listan por etapa


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
    # Sus clientes abiertos, por etapa. El conteo de la etapa es el total;
    # en la lista no se repite al que ya sale arriba en "para hoy", y se
    # corta en CLIENTES_POR_ETAPA (el resto está en la bandeja).
    ya_listados = {l["id"] for l in para_hoy}
    etapas = []
    for etapa in leads["etapas"]:
        resto = [l for l in etapa["leads"] if l["id"] not in ya_listados]
        etapas.append({
            "estado": etapa["estado"],
            "titulo": etapa["titulo"],
            "total": len(etapa["leads"]),
            "leads": resto[:CLIENTES_POR_ETAPA],
            "sin_listar": max(0, len(resto) - CLIENTES_POR_ETAPA),
        })
    cerrados = leads["cerrados"]

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
        "etapas_seguimiento": etapas,
        "total_leads_vendidos": sum(1 for l in cerrados if l["estado"] == leads_chat.ESTADO_VENDIDO),
        "total_leads_descartados": sum(1 for l in cerrados
                                       if l["estado"] == leads_chat.ESTADO_DESCARTADO),
        "leads_nuevos": leads["nuevos"][:LEADS_EN_PORTADA],
        "total_leads_nuevos": len(leads["nuevos"]),
        "total_leads_en_gestion": len(leads["en_gestion"]),
    }

"""
Servicio de reportes de gerencia.

Lee las vistas SQL de la base (reporte_*). Las vistas hacen el trabajo
pesado (agrupar, contar, cruzar tablas); aquí solo las exponemos como
funciones limpias para que la ruta las use, igual que los demás servicios.

Estas vistas contienen datos sensibles del negocio (ventas, ingresos),
por eso solo las lee la conexión admin (service_role); el rol público
no tiene permiso SELECT sobre ellas.
"""

from app.db import repositorios


def ventas_por_usuario(desde=None, hasta=None):
    """
    Cuantas motos ha vendido cada persona en el rango dado.
    Replica la vista reporte_ventas_por_usuario (usuario_nombre,
    total_ventas, primera_venta, ultima_venta) pero filtrable por fecha.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.reporte_ventas_por_usuario(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        nombre = f["usuario_nombre"]
        fecha = f["created_at"]
        if nombre not in agregado:
            agregado[nombre] = {"usuario_nombre": nombre, "total_ventas": 0,
                                "primera_venta": fecha, "ultima_venta": fecha}
        a = agregado[nombre]
        a["total_ventas"] += 1
        if fecha < a["primera_venta"]:
            a["primera_venta"] = fecha
        if fecha > a["ultima_venta"]:
            a["ultima_venta"] = fecha

    return sorted(agregado.values(), key=lambda x: x["total_ventas"], reverse=True)


def ventas_por_semana():
    """Ritmo de ventas semana a semana."""
    return repositorios.reporte_ventas_por_semana()


def motos_mas_consultadas():
    """Ranking de motos por número de consultas (interés)."""
    return repositorios.reporte_motos_consultadas()


def consultas_por_marca():
    """Qué marcas generan más interés (guía de compra de inventario)."""
    return repositorios.reporte_consultas_por_marca()

def permutas_por_usuario():
    """Cuántas permutas ha cerrado cada asesor."""
    return repositorios.reporte_permutas_por_usuario()


def modelos_permutados():
    """Qué modelos se mueven más en permutas (entrantes + salientes)."""
    return repositorios.reporte_modelos_permutados()

def _rango_fechas_valido(desde=None, hasta=None):
    """
    Normaliza y valida un rango de fechas que llega de la URL.
    Ambas en formato 'YYYY-MM-DD' (lo que manda <input type=date>).
    Devuelve (desde_iso, hasta_iso) listos para la consulta, con None
    donde falte o sea invalido. Nunca devuelve un valor crudo del cliente.

    hasta es INCLUSIVO para el usuario: pedir hasta el '2026-09-04'
    incluye todo ese dia. Por eso se suma un dia y el repositorio
    debe filtrar con < hasta_iso (no <=), o se pierden las filas del
    ultimo dia cuando created_at guarda hora.
    """
    from datetime import datetime, timedelta, timezone

    def parsear(v):
        if not v:
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

    d_desde, d_hasta = parsear(desde), parsear(hasta)
    # Rango al reves (desde posterior a hasta) -> se descarta entero.
    if d_desde and d_hasta and d_desde > d_hasta:
        return (None, None)
    desde_iso = d_desde.isoformat() if d_desde else None
    hasta_iso = (d_hasta + timedelta(days=1)).isoformat() if d_hasta else None
    return (desde_iso, hasta_iso)

def ventas_detalle(desde=None, hasta=None, orden="fecha"):
    """
    Cada venta individual, filtrada por rango de fechas y ordenada.
    Valida lo que llega de la URL: 'desde'/'hasta' pasan por el
    validador de rango compartido; 'orden' por lista blanca.
    Nunca se pasa a la consulta un valor crudo del cliente.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    orden_valido = orden if orden in ("fecha", "asesor") else "fecha"
    return repositorios.reporte_ventas_detalle(
        desde=desde_iso, hasta=hasta_iso, orden=orden_valido
    )

def verificar_venta(venta_id, usuario_nombre):
    """Marca una venta como verificada por gerencia."""
    return repositorios.marcar_venta_verificada(venta_id, usuario_nombre)

def compras_por_usuario(desde=None, hasta=None):
    """
    Cuantas motos ha comprado cada persona en el rango dado.
    Misma forma que ventas_por_usuario: usuario_nombre, total_compras,
    primera_compra, ultima_compra. Ordenado por total desc.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.reporte_compras_por_usuario(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        nombre = f["usuario_nombre"]
        fecha = f["created_at"]
        if nombre not in agregado:
            agregado[nombre] = {"usuario_nombre": nombre, "total_compras": 0,
                                "primera_compra": fecha, "ultima_compra": fecha}
        a = agregado[nombre]
        a["total_compras"] += 1
        if fecha < a["primera_compra"]:
            a["primera_compra"] = fecha
        if fecha > a["ultima_compra"]:
            a["ultima_compra"] = fecha

    return sorted(agregado.values(), key=lambda x: x["total_compras"], reverse=True)

def compras_detalle(desde=None, hasta=None, orden="fecha"):
    """Cada compra individual, filtrada por rango de fechas y ordenada."""
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    orden_valido = orden if orden in ("fecha", "asesor") else "fecha"
    return repositorios.reporte_compras_detalle(
        desde=desde_iso, hasta=hasta_iso, orden=orden_valido
    )

def verificar_compra(compra_id, usuario_nombre):
    """Marca una compra como verificada por gerencia."""
    return repositorios.marcar_compra_verificada(compra_id, usuario_nombre)

def documentos_por_vencer():
    """Motos con SOAT o tecno próximos a vencer."""
    return repositorios.motos_documentos_por_vencer()
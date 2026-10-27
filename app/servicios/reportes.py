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
from app.seguridad.validadores import ErrorValidacion


def ventas_por_usuario(desde=None, hasta=None):
    """
    Cuantas motos ha vendido cada persona en el rango dado.
    Se atribuye al asesor que hizo la venta (asesor_nombre), no a quien
    la registró. Forma: asesor_nombre, total_ventas, primera_venta,
    ultima_venta. Ordenado por total desc.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.reporte_ventas_por_usuario(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        nombre = f["asesor_nombre"]
        fecha = f["created_at"]
        if nombre not in agregado:
            agregado[nombre] = {"asesor_nombre": nombre, "total_ventas": 0,
                                "primera_venta": fecha, "ultima_venta": fecha}
        a = agregado[nombre]
        a["total_ventas"] += 1
        if fecha < a["primera_venta"]:
            a["primera_venta"] = fecha
        if fecha > a["ultima_venta"]:
            a["ultima_venta"] = fecha

    return sorted(agregado.values(), key=lambda x: x["total_ventas"], reverse=True)


def ventas_por_semana(desde=None, hasta=None):
    """
    Ritmo de ventas semana a semana, opcionalmente acotado a [desde, hasta]
    por el lunes de cada semana ('semana' es 'YYYY-MM-DD'). Se filtra en
    Python comparando texto ISO; una fecha mal formada se ignora.
    """
    from datetime import datetime

    def valida(v):
        try:
            return datetime.strptime(v, "%Y-%m-%d").strftime("%Y-%m-%d") if v else None
        except (ValueError, TypeError):
            return None

    desde, hasta = valida(desde), valida(hasta)
    filas = repositorios.reporte_ventas_por_semana()
    if desde:
        filas = [f for f in filas if f["semana"] >= desde]
    if hasta:
        filas = [f for f in filas if f["semana"] <= hasta]
    return filas


def motos_mas_consultadas(desde=None, hasta=None, limite=10):
    """
    Modelos más consultados (clics en 'Preguntar por esta moto') en el
    rango dado; sin fechas, los últimos 30 días. Agrupa por marca+modelo:
    varias unidades del mismo modelo suman en una sola entrada. Clics
    crudos (no personas). Forma: [{marca, modelo, consultas}], desc.
    """
    desde, hasta = _rango_por_defecto(desde, hasta, dias=30)
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.intenciones_con_moto(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        moto = f.get("motos") or {}
        marca = " ".join((moto.get("marca") or "").split())
        modelo = " ".join((moto.get("modelo") or "").split())
        if not marca and not modelo:
            continue  # moto retirada del inventario: no hay modelo al que atribuirla
        # Clave sin mayúsculas: 'Nkd 125' y 'NKD 125' son el mismo modelo.
        clave = (marca.upper(), modelo.upper())
        if clave not in agregado:
            agregado[clave] = {"marca": marca, "modelo": modelo, "consultas": 0}
        agregado[clave]["consultas"] += 1

    return sorted(agregado.values(), key=lambda x: x["consultas"], reverse=True)[:limite]


def consultas_por_marca():
    """Qué marcas generan más interés (guía de compra de inventario)."""
    return repositorios.reporte_consultas_por_marca()

def permutas_por_usuario(desde=None, hasta=None):
    """
    Cuántas permutas cerró cada asesor en el rango dado. Se cuenta en
    Python (no en una vista) para poder filtrar por fecha, igual que
    ventas_por_usuario. Forma: usuario_nombre, total_permutas. Orden desc.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.reporte_permutas_por_usuario(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        nombre = f["usuario_nombre"]
        if nombre not in agregado:
            agregado[nombre] = {"usuario_nombre": nombre, "total_permutas": 0}
        agregado[nombre]["total_permutas"] += 1

    return sorted(agregado.values(), key=lambda x: x["total_permutas"], reverse=True)


def modelos_permutados():
    """Qué modelos se mueven más en permutas (entrantes + salientes)."""
    return repositorios.reporte_modelos_permutados()

def _rango_por_defecto(desde, hasta, dias=15):
    """
    Rango por defecto de los paneles de gerencia: si no llegan fechas,
    usa los últimos 'dias' días. Centralizado aquí para que todas las
    vistas de gerencia con filtro de fecha abran con el mismo rango.
    Devuelve (desde, hasta) como strings 'YYYY-MM-DD'.
    """
    from datetime import datetime, timedelta, timezone
    if not desde and not hasta:
        hoy = datetime.now(timezone.utc).date()
        desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
        hasta = hoy.strftime("%Y-%m-%d")
    return desde, hasta

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
    """
    Marca una venta como verificada.

    Antes valida que la venta esté en el alcance de sede del usuario en
    sesión: gerencia/admin verifican cualquiera, el encargado solo las de
    su sede. La guarda vive aquí (no en la ruta) para que proteja
    cualquier camino que llegue a verificar, incluido un POST directo.
    """
    from app.servicios.detalle_ventas import venta_en_alcance
    if not venta_en_alcance(venta_id):
        raise ErrorValidacion("La venta no existe o no pertenece a su sede.", "venta")
    return repositorios.marcar_venta_verificada(venta_id, usuario_nombre)

def compras_por_usuario(desde=None, hasta=None):
    """
    Cuantas motos ha comprado cada persona en el rango dado.
    Se atribuye al asesor que hizo el negocio (asesor_nombre), no a
    quien la registró. Forma: asesor_nombre, total_compras,
    primera_compra, ultima_compra. Ordenado por total desc.
    """
    desde_iso, hasta_iso = _rango_fechas_valido(desde, hasta)
    filas = repositorios.reporte_compras_por_usuario(desde=desde_iso, hasta=hasta_iso)

    agregado = {}
    for f in filas:
        nombre = f["asesor_nombre"]
        fecha = f["created_at"]
        if nombre not in agregado:
            agregado[nombre] = {"asesor_nombre": nombre, "total_compras": 0,
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

# Rangos de precio (COP) del análisis de interés: [minimo, maximo).
# None como máximo = sin tope.
RANGOS_PRECIO = (
    ("Hasta $6M", 0, 6_000_000),
    ("$6–8M", 6_000_000, 8_000_000),
    ("$8–12M", 8_000_000, 12_000_000),
    ("Más de $12M", 12_000_000, None),
)


def interes_por_rango_precio(desde=None, hasta=None):
    """
    Tasa de clics por moto cada 30 días, por rango de precio, mes a mes.

    Normaliza por exposición: un rango con más motos publicadas recibe
    más clics sin ser más atractivo. Para cada mes y rango:
      clics     = intenciones de motos del rango en el mes
      moto_dias = suma de días que cada moto del rango estuvo publicada
                  dentro del mes (publicada_en -> hoy, o -> fecha de venta)
      tasa      = clics / moto_dias * 30

    Meses en hora de Colombia (como ventas_por_semana). desde/hasta son
    'YYYY-MM-DD', hasta inclusivo; sin desde (o inválido), los 6 meses
    hasta 'hasta' (o hasta hoy). Los meses de los bordes se recortan a la
    ventana pedida, para que clics y moto_dias midan el mismo período; los
    meses iniciales sin moto_dias en ningún rango se omiten.

    Forma: {"desde", "hasta" (ventana efectiva), "meses": ["YYYY-MM", ...],
    "series": [{"rango", "tasas", "clics", "moto_dias"}, ...]}, una serie
    por rango, en orden de precio.
    """
    from datetime import datetime, timedelta
    from app.servicios.contratos import HORA_COLOMBIA

    def parsear(v):
        try:
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=HORA_COLOMBIA) if v else None
        except (ValueError, TypeError):
            return None

    def fecha(iso):
        return datetime.fromisoformat(iso)

    def seis_meses_antes(f):
        # El 1 del mes de hace 5 meses: 6 meses de calendario hasta f.
        m = f.year * 12 + f.month - 1 - 5
        return f.replace(year=m // 12, month=m % 12 + 1, day=1,
                         hour=0, minute=0, second=0, microsecond=0)

    ahora = datetime.now(HORA_COLOMBIA)
    inicio, fin = parsear(desde), parsear(hasta)
    fin = fin + timedelta(days=1) if fin else None  # hasta inclusivo
    if inicio and fin and fin <= inicio:
        inicio, fin = None, None  # rango al revés: se descarta entero
    if not inicio:
        inicio = seis_meses_antes(min(fin, ahora) if fin else ahora)
    fin = min(fin or ahora, ahora)  # no hay exposición ni clics en el futuro

    # Ventana efectiva ('YYYY-MM-DD', hasta inclusivo), para que la vista
    # muestre en los inputs las fechas que realmente se usaron.
    ventana = {"desde": inicio.strftime("%Y-%m-%d"),
               "hasta": (fin - timedelta(microseconds=1)).strftime("%Y-%m-%d")}
    if fin <= inicio:
        return {**ventana, "meses": [], "series": [
            {"rango": r[0], "tasas": [], "clics": [], "moto_dias": []} for r in RANGOS_PRECIO]}

    # Meses de la ventana, recortados a [inicio, fin).
    meses = []
    cursor = inicio.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < fin:
        siguiente = cursor.replace(year=cursor.year + cursor.month // 12,
                                   month=cursor.month % 12 + 1)
        meses.append((cursor.strftime("%Y-%m"), max(cursor, inicio), min(siguiente, fin)))
        cursor = siguiente

    def indice_rango(precio):
        for i, (_, minimo, maximo) in enumerate(RANGOS_PRECIO):
            if precio >= minimo and (maximo is None or precio < maximo):
                return i
        return None

    # Fecha de venta por moto: la última venta no anulada.
    vendida_en = {}
    for v in repositorios.fechas_de_venta_activas():
        f = fecha(v["created_at"])
        if v["moto_id"] not in vendida_en or f > vendida_en[v["moto_id"]]:
            vendida_en[v["moto_id"]] = f

    # Moto incluida -> (rango, inicio de exposición, fin de exposición).
    exposicion = {}
    for m in repositorios.motos_para_interes_por_precio():
        if m["estado"] == "vendido":
            if m["id"] not in vendida_en:
                continue  # vendida sin registro en ventas: no se sabe cuándo salió
            fin_exp = vendida_en[m["id"]]
        else:
            fin_exp = ahora
        rango = indice_rango(m["precio"])
        if rango is not None:
            exposicion[m["id"]] = (rango, fecha(m["publicada_en"]), fin_exp)

    n_rangos, n_meses = len(RANGOS_PRECIO), len(meses)
    clics = [[0] * n_meses for _ in range(n_rangos)]
    moto_dias = [[0.0] * n_meses for _ in range(n_rangos)]

    for rango, ini_exp, fin_exp in exposicion.values():
        for j, (_, ini_mes, fin_mes) in enumerate(meses):
            solape = (min(fin_exp, fin_mes) - max(ini_exp, ini_mes)).total_seconds()
            if solape > 0:
                moto_dias[rango][j] += solape / 86400

    for i in repositorios.intenciones_en_rango(inicio.isoformat(), fin.isoformat()):
        if i["moto_id"] not in exposicion:
            continue
        f = fecha(i["created_at"])
        for j, (_, ini_mes, fin_mes) in enumerate(meses):
            if ini_mes <= f < fin_mes:
                clics[exposicion[i["moto_id"]][0]][j] += 1
                break

    # Recortar los meses iniciales sin exposición en ningún rango (antes de
    # la migración 009 no hay publicada_en): el gráfico arranca donde hay datos.
    primero = next((j for j in range(n_meses)
                    if any(moto_dias[r][j] > 0 for r in range(n_rangos))), n_meses)

    series = []
    for r, (etiqueta, _, _) in enumerate(RANGOS_PRECIO):
        c_r, d_r = clics[r][primero:], moto_dias[r][primero:]
        series.append({
            "rango": etiqueta,
            "tasas": [round(c / d * 30, 2) if d else 0 for c, d in zip(c_r, d_r)],
            "clics": c_r,
            "moto_dias": [round(d, 1) for d in d_r],
        })
    return {**ventana, "meses": [m[0] for m in meses[primero:]], "series": series}


def documentos_por_vencer():
    """Motos con SOAT o tecno próximos a vencer."""
    return repositorios.motos_documentos_por_vencer()
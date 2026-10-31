"""
Servicio de avalúo: "¿Cuánto vale mi moto?".

Estima el valor de una moto usada a partir de las motos del mismo
marca y modelo que ya pasaron por el negocio. El precio de cada
comparable es el de su venta real (ventas.precio_venta) si la hubo;
si no, el publicado (motos.precio). El publicado NO es una venta: solo
rellena el hueco cuando no hay venta registrada.

Solo sale información agregada (percentiles y conteo): nunca el precio
de una moto concreta ni datos de una venta.

Entrada externa (la URL): marca y modelo se validan contra la lista de
modelos que existen en la base (lista blanca), año y km por rango.
"""

from datetime import date

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion

# Comparables con año dentro de ±VENTANA_ANIOS del consultado. Si quedan
# menos de MIN_COMPARABLES_ANIO, se usan todos los años del modelo.
VENTANA_ANIOS = 2
MIN_COMPARABLES_ANIO = 3

# Precios redondeados a este múltiplo: un avalúo no tiene precisión
# de pesos, y un número redondo no aparenta una exactitud que no hay.
REDONDEO = 50_000

ANIO_MIN = 1980
KM_MAX = 1_000_000


def modelos_por_marca() -> dict:
    """
    {marca: [modelos]} con las combinaciones que existen en la base,
    ordenadas. Alimenta los desplegables y la validación (lista blanca).
    """
    modelos = {}
    for fila in repositorios.pares_marca_modelo():
        marca, modelo = fila.get("marca"), fila.get("modelo")
        if marca and modelo:
            modelos.setdefault(marca, set()).add(modelo)
    return {marca: sorted(modelos[marca]) for marca in sorted(modelos)}


def _entero(valor, campo, minimo, maximo, obligatorio):
    if valor is None or str(valor).strip() == "":
        if obligatorio:
            raise ErrorValidacion(f"El campo {campo} es obligatorio.", campo)
        return None
    try:
        numero = int(str(valor).strip())
    except ValueError:
        raise ErrorValidacion(f"El campo {campo} debe ser un número entero.", campo)
    if numero < minimo or numero > maximo:
        raise ErrorValidacion(f"El campo {campo} debe estar entre {minimo} y {maximo}.", campo)
    return numero


def validar_consulta(args) -> dict:
    """
    Valida los parámetros crudos (?marca=&modelo=&anio=&km=).
    Devuelve {marca, modelo, anio, km} o lanza ErrorValidacion.
    El km es opcional: sin él, el estimado es la mediana.
    """
    marca = (args.get("marca") or "").strip()
    modelo = (args.get("modelo") or "").strip()
    if modelo not in modelos_por_marca().get(marca, []):
        raise ErrorValidacion("Elige una marca y un modelo de la lista.", "modelo")
    return {
        "marca": marca,
        "modelo": modelo,
        "anio": _entero(args.get("anio"), "año", ANIO_MIN, date.today().year + 1, True),
        "km": _entero(args.get("km"), "kilometraje", 0, KM_MAX, False),
    }


def _percentil(ordenados, p):
    """Percentil p (0-1) con interpolación lineal, sobre una lista ordenada."""
    pos = (len(ordenados) - 1) * p
    abajo = int(pos)
    arriba = min(abajo + 1, len(ordenados) - 1)
    return ordenados[abajo] + (ordenados[arriba] - ordenados[abajo]) * (pos - abajo)


def _rango_percentil(valor, ordenados):
    """
    Qué fracción (0-1) de la lista queda por debajo de 'valor'. Los
    empates cuentan la mitad, para que un km igual a todos quede al medio.
    """
    debajo = sum(1 for v in ordenados if v < valor)
    iguales = sum(1 for v in ordenados if v == valor)
    return (debajo + iguales / 2) / len(ordenados)


def _redondear(valor):
    return int(round(valor / REDONDEO)) * REDONDEO


def _confianza(n):
    if n >= 8:
        return "alta"
    if n >= 3:
        return "media"
    return "baja"


def _comparables(marca, modelo):
    """[{anio, km, precio}] del modelo, con el precio ya resuelto."""
    comparables = []
    for moto in repositorios.motos_con_venta_activa(marca, modelo):
        # Si por error hubiera dos ventas activas, vale la más reciente.
        ventas = sorted(moto.get("ventas") or [], key=lambda v: v["id"])
        precio = ventas[-1]["precio_venta"] if ventas else moto.get("precio")
        if precio and precio > 0:
            comparables.append({
                "anio": moto.get("anio"),
                "km": moto.get("kilometraje"),
                "precio": precio,
            })
    return comparables


def _estimar(comparables, anio, km=None) -> dict:
    """
    Estima el valor de una moto a partir de sus comparables
    ([{anio, km, precio}]). Función pura: no toca la base. Devuelve
    {"sin_datos": True} si no hay con qué comparar.
    """
    if not comparables:
        return {"sin_datos": True}

    cercanos = [c for c in comparables
                if c["anio"] is not None and abs(c["anio"] - anio) <= VENTANA_ANIOS]
    usados = cercanos if len(cercanos) >= MIN_COMPARABLES_ANIO else comparables

    precios = sorted(c["precio"] for c in usados)
    rango_min = _percentil(precios, 0.25)
    rango_max = _percentil(precios, 0.75)
    mediana = _percentil(precios, 0.5)

    # Poco km -> cerca de rango_max; mucho km -> cerca de rango_min.
    kms = sorted(c["km"] for c in usados if c["km"] is not None)
    if km is None or not kms:
        estimado = mediana
    else:
        estimado = rango_max - _rango_percentil(km, kms) * (rango_max - rango_min)

    anios = [c["anio"] for c in usados if c["anio"] is not None]
    return {
        "estimado": _redondear(estimado),
        "rango_min": _redondear(rango_min),
        "rango_max": _redondear(rango_max),
        "n_comparables": len(usados),
        "confianza": _confianza(len(usados)),
        "anio_desde": min(anios) if anios else None,
        "anio_hasta": max(anios) if anios else None,
    }


def avaluo(marca, modelo, anio, km=None) -> dict:
    """Orquesta: trae comparables de la base y delega el cálculo a la función pura."""
    return _estimar(_comparables(marca, modelo), anio, km)

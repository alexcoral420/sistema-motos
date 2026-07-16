"""
Servicio de catálogo: filtrado de motos para el público.

Los filtros llegan por la URL (?marca=yamaha&sede=2). Eso es ENTRADA
EXTERNA: cualquiera puede escribir lo que quiera en la barra del
navegador. Antes de que toque la base de datos, se valida todo.

Riesgo particular del texto de búsqueda: se inserta dentro de la
sintaxis de consulta de Supabase, donde la coma y el punto tienen
significado. Un texto sin validar podría inyectar condiciones. Por eso
usamos lista blanca estricta: solo letras, números y espacios.
"""

import re

from app.db import repositorios
from app.servicios import sedes

_TEXTO_PERMITIDO = re.compile(r"^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ\s\-]+$")

_PRECIO_MAX = 999_999_999


def _limpiar_texto(valor):
    """
    Valida el texto de búsqueda con lista blanca.
    Devuelve el texto limpio, o None si no es aceptable.
    """
    if not valor:
        return None
    texto = valor.strip()
    if not texto or len(texto) > 50:
        return None
    if not _TEXTO_PERMITIDO.match(texto):
        return None
    return texto


def _limpiar_entero(valor, minimo=0, maximo=_PRECIO_MAX):
    """
    Convierte y valida un número de la URL.
    Devuelve el entero, o None si no es válido o está fuera de rango.
    """
    if valor is None or valor == "":
        return None
    try:
        numero = int(valor)
    except (ValueError, TypeError):
        return None
    if numero < minimo or numero > maximo:
        return None
    return numero


def limpiar_filtros(args) -> dict:
    """
    Toma los parámetros crudos de la URL y devuelve filtros seguros.
    Lo que no supere la validación se descarta en silencio: un filtro
    raro en la URL no debe romper el catálogo público.
    """
    marca = args.get("marca") or None
    if marca and marca not in repositorios.obtener_marcas_disponibles():
        marca = None

    sede_id = _limpiar_entero(args.get("sede"), minimo=1)
    if sede_id and str(sede_id) not in sedes.ids_validos():
        sede_id = None

    precio_min = _limpiar_entero(args.get("precio_min"))
    precio_max = _limpiar_entero(args.get("precio_max"))

    if precio_min is not None and precio_max is not None and precio_min > precio_max:
        precio_min = None
        precio_max = None

    return {
        "marca": marca,
        "sede_id": sede_id,
        "precio_min": precio_min,
        "precio_max": precio_max,
        "texto": _limpiar_texto(args.get("q")),
    }


def buscar_motos(args) -> dict:
    """
    Punto de entrada del catálogo filtrado.
    Devuelve las motos que cumplen los filtros, las opciones de los
    selectores, y los filtros aplicados (para recordar lo elegido).
    """
    filtros = limpiar_filtros(args)
    return {
        "motos": repositorios.obtener_motos_filtradas(filtros),
        "marcas": repositorios.obtener_marcas_disponibles(),
        "sedes": sedes.listar_sedes(),
        "filtros": filtros,
    }
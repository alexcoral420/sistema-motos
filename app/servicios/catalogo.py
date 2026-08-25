"""
Servicio de catálogo: filtrado de motos para el público.

Los filtros llegan por la URL (?marca=yamaha&sede=2). Eso es ENTRADA
EXTERNA: cualquiera puede escribir lo que quiera en la barra del
navegador. Antes de que toque la base de datos, se valida todo.

Riesgo particular del texto de búsqueda: se inserta dentro de la
sintaxis de consulta de Supabase, donde la coma y el punto tienen
significado. Un texto sin validar podría inyectar condiciones. Por eso
usamos lista blanca estricta: solo letras, números y espacios.

Selección múltiple: marca, cilindraje y año aceptan varias opciones
(?marca=BAJAJ&marca=YAMAHA). Se leen con getlist() y se valida cada
elemento por separado, con un tope de cuántos se aceptan.
"""

import re

from app.db import repositorios
from app.servicios import sedes

_TEXTO_PERMITIDO = re.compile(r"^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ\s\-]+$")

_PRECIO_MAX = 999_999_999

# Tope de opciones por criterio: sin esto, alguien podría mandar 500
# marcas en la URL y hacer pesada la consulta.
_MAX_OPCIONES = 12


# ============================================================
# RANGOS: definidos UNA vez, aquí.
#
# La clave ("hasta-125") es lo que viaja en la URL. Validar es tan
# simple como comprobar que la clave exista en el diccionario: lista
# blanca por construcción, no hay forma de inyectar nada.
#
# min/max en None significa "sin límite por ese lado".
# ============================================================

RANGOS_CILINDRAJE = {
    "hasta-125": {"etiqueta": "Hasta 125cc",  "min": None, "max": 125},
    "126-150":   {"etiqueta": "126 a 150cc",  "min": 126,  "max": 150},
    "151-200":   {"etiqueta": "151 a 200cc",  "min": 151,  "max": 200},
    "mas-200":   {"etiqueta": "Más de 200cc", "min": 201,  "max": None},
}

RANGOS_ANIO = {
    "2023-mas":  {"etiqueta": "2023 o más nuevo", "min": 2023, "max": None},
    "2020-2022": {"etiqueta": "2020 a 2022",      "min": 2020, "max": 2022},
    "2017-2019": {"etiqueta": "2017 a 2019",      "min": 2017, "max": 2019},
    "hasta-2016": {"etiqueta": "2016 o anterior", "min": None, "max": 2016},
}

RANGOS_PRECIO = {
    "hasta-6m": {"etiqueta": "Hasta $6M",   "min": None,       "max": 5_999_999},
    "6-8m":     {"etiqueta": "$6M a $8M",   "min": 6_000_000,  "max": 7_999_999},
    "8-12m":    {"etiqueta": "$8M a $12M",  "min": 8_000_000,  "max": 11_999_999},
    "mas-12m":  {"etiqueta": "Más de $12M", "min": 12_000_000, "max": None},
}


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


def _limpiar_claves(valores, rangos):
    """
    De una lista de claves recibida por URL, deja solo las que existen
    en el diccionario de rangos. Todo lo demás se descarta.
    """
    if not valores:
        return []
    limpias = [v for v in valores[:_MAX_OPCIONES] if v in rangos]
    # Sin duplicados, conservando el orden de definición.
    return [c for c in rangos if c in limpias]


def _a_intervalos(claves, rangos):
    """
    Traduce las claves elegidas a pares (min, max) concretos.

    El repositorio no debe conocer nombres como "hasta-125": eso es
    vocabulario de negocio. Aquí lo convertimos en números, y la capa
    de datos solo ve intervalos.
    """
    return [(rangos[c]["min"], rangos[c]["max"]) for c in claves]


def limpiar_filtros(args) -> dict:
    """
    Toma los parámetros crudos de la URL y devuelve filtros seguros.
    Lo que no supere la validación se descarta en silencio: un filtro
    raro en la URL no debe romper el catálogo público.
    """
    # --- Marcas (selección múltiple) ---
    disponibles = repositorios.obtener_marcas_disponibles()
    marcas = [m for m in args.getlist("marca")[:_MAX_OPCIONES] if m in disponibles]

    # --- Sede ---
    sede_id = _limpiar_entero(args.get("sede"), minimo=1)
    if sede_id and str(sede_id) not in sedes.ids_validos():
        sede_id = None

        # --- Precio (selección múltiple por rangos) ---
    claves_precio = _limpiar_claves(args.getlist("precio"), RANGOS_PRECIO)



    # --- Cilindraje y año (selección múltiple por rangos) ---
    claves_cc = _limpiar_claves(args.getlist("cc"), RANGOS_CILINDRAJE)
    claves_anio = _limpiar_claves(args.getlist("anio"), RANGOS_ANIO)

    return {
        "marcas": marcas,
        "sede_id": sede_id,
        "precio": claves_precio,
        "precio_rangos": _a_intervalos(claves_precio, RANGOS_PRECIO),
        "texto": _limpiar_texto(args.get("q")),
        # Claves: para volver a marcar las casillas en la página.
        "cc": claves_cc,
        "anio": claves_anio,
        # Intervalos: para que el repositorio arme la consulta.
        "cilindraje_rangos": _a_intervalos(claves_cc, RANGOS_CILINDRAJE),
        "anio_rangos": _a_intervalos(claves_anio, RANGOS_ANIO),
    }


def contar_filtros_activos(filtros) -> int:
    """
    Cuántos criterios hay aplicados. Se muestra en el botón del panel
    para que el cliente sepa por qué está viendo pocos resultados.
    """
    activos = 0
    if filtros.get("marcas"):
        activos += len(filtros["marcas"])
    if filtros.get("cc"):
        activos += len(filtros["cc"])
    if filtros.get("anio"):
        activos += len(filtros["anio"])
    if filtros.get("sede_id"):
        activos += 1
    if filtros.get("precio"):
        activos += len(filtros["precio"])
    return activos


MOTOS_POR_PAGINA = 1


def buscar_motos(args) -> dict:
    """
    Punto de entrada del catálogo filtrado.

    Devuelve las motos de la página pedida, las opciones de los selectores,
    los filtros aplicados y los datos de paginación.
    """
    filtros = limpiar_filtros(args)

    # La página viene de la URL: entrada externa, se valida como todo lo demás.
    pagina = _limpiar_entero(args.get("pagina"), minimo=1, maximo=1000) or 1

    motos, total = repositorios.obtener_motos_filtradas(
        filtros, limite=MOTOS_POR_PAGINA, pagina=pagina
    )

    # Cuántas páginas hacen falta para mostrar 'total' motos.
    # El -1 y +1 redondean hacia arriba sin usar decimales: 16 motos en
    # páginas de 15 son 2 páginas, no 1.
    total_paginas = max(1, (total + MOTOS_POR_PAGINA - 1) // MOTOS_POR_PAGINA)

    # Si alguien pide una página que no existe, lo llevamos a la última.
    if pagina > total_paginas:
        pagina = total_paginas
        motos, total = repositorios.obtener_motos_filtradas(
            filtros, limite=MOTOS_POR_PAGINA, pagina=pagina
        )

    return {
        "motos": motos,
        "marcas": repositorios.obtener_marcas_disponibles(),
        "sedes": sedes.listar_sedes(),
        "filtros": filtros,
        "rangos_cc": RANGOS_CILINDRAJE,
        "rangos_anio": RANGOS_ANIO,
        "rangos_precio": RANGOS_PRECIO,
        "filtros_activos": contar_filtros_activos(filtros),
        "pagina": pagina,
        "total_paginas": total_paginas,
        "total_motos": total,
    }
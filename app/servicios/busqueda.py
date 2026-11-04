"""
Búsqueda en el panel administrativo.

Los filtros llegan por la URL (?id=108&placa=ABC12). Eso es ENTRADA
EXTERNA, aunque venga de un usuario autenticado: se valida igual.

Criterio (igual que en el catálogo público): lo que no supera la
validación se DESCARTA en silencio. Un filtro raro no debe romper el
panel; simplemente no se aplica.
"""

import csv
import io
import re

from app.db import repositorios
from app.servicios import sedes
from app.servicios.inventario import ESTADOS_MOTO
from app.seguridad.tiempo import hoy_colombia

# Placas colombianas: letras y números, sin símbolos. Lista blanca
# estricta -> nada de comas, comillas ni caracteres con significado
# en la sintaxis de la consulta.
_PLACA_PERMITIDA = re.compile(r"^[a-zA-Z0-9]{1,10}$")


def _limpiar_id(valor):
    """Convierte el id a entero válido, o None si no lo es."""
    if not valor:
        return None
    try:
        numero = int(valor)
    except (ValueError, TypeError):
        return None
    return numero if numero > 0 else None


def _limpiar_placa(valor):
    """Valida la placa con lista blanca. None si no es aceptable."""
    if not valor:
        return None
    placa = valor.strip().upper()
    if not _PLACA_PERMITIDA.match(placa):
        return None
    return placa

def _limpiar_estado(valor):
    """Estado dentro de la lista blanca, o None."""
    if not valor:
        return None
    estado = valor.strip().lower()
    return estado if estado in ESTADOS_MOTO else None

def _limpiar_sede(valor):
    """Sede válida contra las sedes reales (lista blanca), o None."""
    if not valor:
        return None
    sede = str(valor).strip()
    return sede if sede in sedes.ids_validos() else None

def buscar(args) -> dict:
    moto_id = _limpiar_id(args.get("id"))
    placa = _limpiar_placa(args.get("placa"))
    estado = _limpiar_estado(args.get("estado"))
    sede = _limpiar_sede(args.get("sede"))

    return {
        "motos": repositorios.buscar_motos_admin(moto_id, placa, estado, sede),
        "filtros": {"id": moto_id, "placa": placa,
                    "estado": estado, "sede": sede},
        "sedes": sedes.listar_sedes(),
    }


# ============================================================
#  EXPORTAR CSV (inventario del panel)
# ============================================================

COLUMNAS_CSV = (("placa", "placa"), ("modelo", "modelo"),
                ("año", "anio"), ("precio", "precio"))

# Excel interpreta como fórmula una celda que empieza con estos
# caracteres (inyección CSV): se neutraliza con una comilla delante.
_INICIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _celda_csv(valor):
    if valor is None:
        return ""
    if isinstance(valor, str) and valor.startswith(_INICIO_FORMULA):
        return "'" + valor
    return valor


def generar_csv(filas) -> bytes:
    """CSV con las columnas de COLUMNAS_CSV. UTF-8 con BOM para que
    Excel lea bien las tildes."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\r\n")
    escritor.writerow([titulo for titulo, _ in COLUMNAS_CSV])
    for fila in filas:
        escritor.writerow([_celda_csv(fila.get(campo)) for _, campo in COLUMNAS_CSV])
    return salida.getvalue().encode("utf-8-sig")


def exportar_csv(args):
    """
    (contenido, nombre_archivo) del CSV del inventario con los filtros
    de sede y estado de la URL, validados igual que en buscar(). Trae
    TODAS las filas que cumplen, no solo las que se ven en pantalla.
    """
    estado = _limpiar_estado(args.get("estado"))
    sede = _limpiar_sede(args.get("sede"))
    filas = repositorios.motos_para_exportar(estado, sede)
    nombre = f"inventario_{hoy_colombia():%Y%m%d}.csv"
    return generar_csv(filas), nombre
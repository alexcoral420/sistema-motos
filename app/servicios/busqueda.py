"""
Búsqueda en el panel administrativo.

Los filtros llegan por la URL (?id=108&placa=ABC12). Eso es ENTRADA
EXTERNA, aunque venga de un usuario autenticado: se valida igual.

Criterio (igual que en el catálogo público): lo que no supera la
validación se DESCARTA en silencio. Un filtro raro no debe romper el
panel; simplemente no se aplica.
"""

import re

from app.db import repositorios
from app.servicios import sedes

# Placas colombianas: letras y números, sin símbolos. Lista blanca
# estricta -> nada de comas, comillas ni caracteres con significado
# en la sintaxis de la consulta.
_PLACA_PERMITIDA = re.compile(r"^[a-zA-Z0-9]{1,10}$")
_ESTADOS_VALIDOS = ("disponible", "reservado", "vendido")


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
    return estado if estado in _ESTADOS_VALIDOS else None

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
"""
Servicio de sedes: la lógica de negocio de los puntos de venta.

Cada moto pertenece a una sede (clave foránea sede_id). Este servicio
expone las operaciones de negocio sobre sedes, sin que las rutas ni
los templates sepan cómo se guardan.
"""

from app.db import repositorios


def listar_sedes():
    """Sedes activas, para selectores y para mostrar al público."""
    return repositorios.obtener_sedes_activas()


def obtener_sede(id: int):
    """Una sede por su id."""
    return repositorios.obtener_sede_por_id(id)


def ids_validos() -> list:
    """
    Los ids de sede que se aceptan como válidos en un formulario.

    Se calculan desde la BASE DE DATOS, no desde una lista fija en el
    código. Así, cuando agregues una sede nueva, el validador la acepta
    automáticamente — sin tocar código. Lista blanca dinámica.
    """
    return [str(s["id"]) for s in listar_sedes()]
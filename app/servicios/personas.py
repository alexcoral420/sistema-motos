"""
Servicio de personas: clientes con los que la empresa hace operaciones.

Una misma persona puede ser comprador en una venta (ventas.comprador_id)
y vendedor en una compra (compras.vendedor_id). El rol lo da la columna
que la referencia, no la tabla. Aquí vive la regla de identidad: una
persona es su cédula (normalizada), y nunca se duplica.
"""

import re

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion

# Tras quitar puntos, espacios y guiones: solo letras y dígitos (cédula,
# cédula de extranjería, pasaporte), con largo acotado.
_CEDULA_PERMITIDA = re.compile(r"^[A-Za-z0-9]{5,15}$")


def normalizar_cedula(texto) -> str:
    """
    Quita puntos, espacios y guiones: "1.234.567-8" -> "12345678".
    Lanza ErrorValidacion si viene vacía o no queda algo razonable.
    """
    limpia = re.sub(r"[.\s-]", "", texto or "")
    if not limpia:
        raise ErrorValidacion("La cédula es obligatoria.", "cedula")
    if not _CEDULA_PERMITIDA.match(limpia):
        raise ErrorValidacion(
            "La cédula no es válida: solo números y letras, entre 5 y 15 caracteres.",
            "cedula")
    return limpia


def obtener_o_crear(datos: dict) -> int:
    """
    Devuelve el id de la persona con esa cédula, creándola si no existe.

    datos: nombre, cedula, telefono, correo.
    Si ya existe se reutiliza TAL CUAL: no se actualizan nombre,
    teléfono ni correo (mismo comportamiento que antes del refactor).
    """
    cedula = normalizar_cedula(datos.get("cedula"))

    existente = repositorios.buscar_persona_por_cedula(cedula)
    if existente:
        return existente["id"]

    try:
        nueva = repositorios.crear_persona({
            "nombre": (datos.get("nombre") or "").strip(),
            "cedula": cedula,
            "telefono": (datos.get("telefono") or "").strip() or None,
            "correo": (datos.get("correo") or "").strip() or None,
        })
        return nueva["id"]
    except repositorios.RegistroDuplicado:
        # Otro registro creó la misma cédula entre la búsqueda y el
        # insert (el unique lo frenó): la buscamos y la reutilizamos.
        existente = repositorios.buscar_persona_por_cedula(cedula)
        if existente:
            return existente["id"]
        raise

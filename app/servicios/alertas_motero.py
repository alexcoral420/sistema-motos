"""
Alertas del motero ("Mi espacio") y sus dispositivos push: validación y
decisiones puras. Sin red ni base: se prueba sin Supabase.

Lo usa el blueprint del motero, que tiene prohibido el cliente service_role:
NO importa app.db.repositorios ni nada que lo arrastre (lo verifica
tests/test_cuentas_motero.py). Solo módulos neutrales de app.seguridad.

Fase A: solo la alerta de crédito. El motero pone la fecha de su próxima
cuota (sin monto ni entidad: no se piden datos financieros que no hacen
falta) y la alerta queda mensual, con aviso 3 días y 1 día antes. El envío
es la Fase B.
"""

import calendar
from datetime import date, timedelta

from app.seguridad.suscripcion_push import validar_suscripcion
from app.seguridad.tiempo import fecha_legible, hoy_colombia
from app.seguridad.validadores import ErrorValidacion

# Alerta de crédito: lo fijo lo decide el servidor, no el formulario.
TIPO_CREDITO = "credito"
UMBRALES_CREDITO = (3, 1)

# Rango de la fecha de la próxima cuota. Hacia atrás se tolera un mes
# (alguien que acaba de pagar pone la fecha de la cuota que pagó: como la
# alerta es mensual, igual le avisa de la siguiente); hacia adelante, un año.
DIAS_ATRAS_MAX_CREDITO = 31
DIAS_ADELANTE_MAX_CREDITO = 366

MAX_ALERTAS_POR_MOTERO = 20

MENSAJE_TOPE_ALERTAS = f"Puedes tener hasta {MAX_ALERTAS_POR_MOTERO} alertas."
MENSAJE_ALERTA_NO_ENCONTRADA = "Esa alerta no existe o no es tuya."
MENSAJE_FECHA_CUOTA_INVALIDA = "La fecha de la cuota no es válida."

# Errores de PostgREST (campo `code` de APIError) al escribir una alerta o
# un dispositivo. Lo que no está aquí cae en el genérico.
MENSAJES_ERROR_ALERTA = {
    "23514": "Alguno de los datos está fuera del rango permitido.",
    "42501": "No tienes permiso para hacer eso.",
    "PGRST301": "Tu sesión venció. Ingresa de nuevo.",
}
MENSAJE_ERROR_GENERICO = "No pudimos guardar el cambio. Intenta de nuevo en un momento."

NOMBRES_TIPO = {
    "credito": "Cuota del crédito",
    "soat": "SOAT",
    "tecno": "Tecnomecánica",
    "aceite": "Cambio de aceite",
    "frenos": "Frenos",
    "kit_arrastre": "Kit de arrastre",
    "otro": "Otro",
}


def _hoy() -> date:
    return hoy_colombia()


def rango_fecha_credito(hoy: date = None):
    """(mínima, máxima) aceptadas para la fecha de la cuota; el formulario las usa como min/max."""
    hoy = hoy or _hoy()
    return (hoy - timedelta(days=DIAS_ATRAS_MAX_CREDITO),
            hoy + timedelta(days=DIAS_ADELANTE_MAX_CREDITO))


def validar_alerta_credito(form) -> dict:
    """
    Valida el formulario de la alerta de crédito (solo `fecha_cuota`) y
    devuelve la fila a insertar, sin usuario_id (lo pone la ruta desde la
    sesión). Tipo, modo, recurrencia y umbrales los fija el servidor:
    aunque el formulario los mande, se ignoran.
    """
    valor = form.get("fecha_cuota")
    if valor in (None, ""):
        raise ErrorValidacion("Pon la fecha de tu próxima cuota.", "fecha_cuota")
    if not isinstance(valor, str):
        raise ErrorValidacion(MENSAJE_FECHA_CUOTA_INVALIDA, "fecha_cuota")
    try:
        fecha = date.fromisoformat(valor.strip())
    except ValueError:
        raise ErrorValidacion(MENSAJE_FECHA_CUOTA_INVALIDA, "fecha_cuota")

    minima, maxima = rango_fecha_credito()
    if fecha < minima:
        raise ErrorValidacion(
            "Esa fecha ya pasó hace más de un mes. Pon la de tu próxima cuota.", "fecha_cuota")
    if fecha > maxima:
        raise ErrorValidacion(
            "La fecha no puede estar a más de un año. Pon la de tu próxima cuota.", "fecha_cuota")

    return {
        "tipo": TIPO_CREDITO,
        "modo": "fecha",
        "recurrencia": "mensual",
        "fecha_objetivo": fecha.isoformat(),
        "umbrales_dias": list(UMBRALES_CREDITO),
    }


def validar_dispositivo(datos) -> dict:
    """
    Valida el JSON de POST /mi-espacio/dispositivos ({"suscripcion": {...}})
    y devuelve la suscripción reconstruida (endpoint en la lista de
    servicios de push, claves con el largo correcto).
    """
    if not isinstance(datos, dict):
        raise ErrorValidacion("La solicitud no es válida.")
    return {"suscripcion": validar_suscripcion(datos.get("suscripcion"))}


def mensaje_error_alerta(codigo) -> str:
    return MENSAJES_ERROR_ALERTA.get(codigo or "", MENSAJE_ERROR_GENERICO)


def _sumar_meses(ancla: date, meses: int) -> date:
    """El mismo día del ancla, `meses` después; si ese mes es más corto, su último día."""
    total = ancla.year * 12 + ancla.month - 1 + meses
    anio, mes = divmod(total, 12)
    mes += 1
    return date(anio, mes, min(ancla.day, calendar.monthrange(anio, mes)[1]))


def proxima_ocurrencia(ancla: date, recurrencia: str, hoy: date):
    """
    Primera ocurrencia de la alerta en `hoy` o después. Función pura.

    Cada ocurrencia se calcula desde el ancla (no desde la anterior), así
    una cuota del 31 cae el 28/29 en febrero y vuelve al 31 en marzo.
    'ninguna' -> el ancla si no pasó, si no None.
    """
    if recurrencia == "ninguna":
        return ancla if ancla >= hoy else None
    paso = {"mensual": 1, "anual": 12}.get(recurrencia)
    if paso is None:
        raise ValueError(f"Recurrencia desconocida: {recurrencia}")
    if ancla >= hoy:
        return ancla
    # Salto directo cerca de hoy y se ajusta: sin recorrer mes a mes.
    meses = ((hoy.year - ancla.year) * 12 + hoy.month - ancla.month) // paso * paso
    ocurrencia = _sumar_meses(ancla, meses)
    while ocurrencia < hoy:
        meses += paso
        ocurrencia = _sumar_meses(ancla, meses)
    return ocurrencia


def para_mostrar(alertas, hoy: date = None) -> list:
    """Agrega a cada alerta lo que la página muestra: nombre del tipo y próxima fecha legible."""
    hoy = hoy or _hoy()
    resultado = []
    for a in alertas:
        fila = dict(a)
        fila["nombre"] = NOMBRES_TIPO.get(a.get("tipo"), "Alerta")
        proxima = None
        if a.get("modo") == "fecha" and a.get("fecha_objetivo"):
            proxima = proxima_ocurrencia(date.fromisoformat(a["fecha_objetivo"]),
                                         a.get("recurrencia") or "ninguna", hoy)
        fila["proxima"] = fecha_legible(proxima) if proxima else None
        resultado.append(fila)
    return resultado

"""
Hora de Colombia, en un módulo neutral.

Neutral = sin imports de app, supabase ni config (lo verifica un test):
lo usan tanto los servicios del panel como el blueprint del motero, que
tiene prohibido arrastrar el repositorio del admin.
"""

from datetime import date, datetime, timedelta, timezone

# Hora de Colombia (America/Bogota): UTC-5 fijo, sin horario de verano
# desde 1993. Offset fijo en vez de ZoneInfo("America/Bogota") porque
# ZoneInfo necesita la base de zonas del sistema o el paquete tzdata,
# que en Windows no viene y en el contenedor no está garantizada.
HORA_COLOMBIA = timezone(timedelta(hours=-5))


def hoy_colombia() -> date:
    """La fecha de hoy en Colombia (no la del servidor, que corre en UTC)."""
    return datetime.now(HORA_COLOMBIA).date()


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def fecha_legible(fecha: date) -> str:
    """'15 de marzo de 2027': como se le muestra una fecha al cliente."""
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}"


def momento_legible(iso) -> str:
    """
    '10 de noviembre, 3:45 p. m.' en hora de Colombia, a partir de un
    timestamp ISO de la base (UTC). '' si no hay fecha o no se puede leer.
    """
    if not iso:
        return ""
    try:
        momento = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    local = momento.astimezone(HORA_COLOMBIA)
    hora = local.hour % 12 or 12
    sufijo = "a. m." if local.hour < 12 else "p. m."
    return f"{local.day} de {MESES[local.month - 1]}, {hora}:{local.minute:02d} {sufijo}"

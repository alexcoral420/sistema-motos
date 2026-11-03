"""
Alertas del motero ("Mi espacio") y sus dispositivos push: validación y
decisiones puras. Sin red ni base: se prueba sin Supabase.

Lo usa el blueprint del motero, que tiene prohibido el cliente service_role:
NO importa app.db.repositorios ni nada que lo arrastre (lo verifica
tests/test_cuentas_motero.py). Solo módulos neutrales de app.seguridad.

Alertas por fecha (el envío diario es scripts/enviar_alertas.py; aquí
vive su decisión pura, avisos_a_enviar):
  - Crédito: el motero pone la fecha de su próxima cuota (sin monto ni
    entidad: no se piden datos financieros que no hacen falta). Mensual,
    aviso 3 días y 1 día antes.
  - SOAT y tecnomecánica, por moto: la fecha de vencimiento. Anuales,
    aviso 30, 15, 7 y 1 día antes. Una de cada tipo por moto (índice
    único parcial, migración 024).

fecha_objetivo es el ancla y nunca se reescribe, ni al pasar un ciclo: la
fecha de cada ocurrencia la calcula proxima_ocurrencia() desde el ancla, y
esa fecha (ISO) es el `ciclo` con el que se registra cada aviso enviado.
"""

import calendar
from datetime import date, timedelta

from app.seguridad.suscripcion_push import validar_suscripcion
from app.seguridad.tiempo import fecha_legible, hoy_colombia
from app.seguridad.validadores import ErrorValidacion

# Reglas de cada alerta por fecha: única fuente para la validación, la
# fila que se guarda y los límites del formulario. Recurrencia y umbrales
# los fija el servidor; el formulario solo manda la fecha.
#
# Hacia atrás se tolera un mes en todas: quien acaba de pagar la cuota (o
# tiene el documento recién vencido) igual recibe el aviso del ciclo
# siguiente. Hacia adelante: un año para la cuota y el SOAT (dura un año);
# dos para la tecno (la moto nueva hace la primera revisión a los 2 años
# de matriculada).
TIPOS_ALERTA_FECHA = {
    "credito": {
        "recurrencia": "mensual",
        "umbrales": (3, 1),
        "dias_atras": 31,
        "dias_adelante": 366,
        "campo": "fecha_cuota",
        "aviso": {
            "titulo": "Se acerca tu cuota",
            "sujeto": "Tu cuota",
            "cierre": "Págala a tiempo para evitar intereses de mora.",
        },
        "mensajes": {
            "vacia": "Pon la fecha de tu próxima cuota.",
            "invalida": "La fecha de la cuota no es válida.",
            "pasada": "Esa fecha ya pasó hace más de un mes. Pon la de tu próxima cuota.",
            "futura": "La fecha no puede estar a más de un año. Pon la de tu próxima cuota.",
        },
    },
    "soat": {
        "recurrencia": "anual",
        "umbrales": (30, 15, 7, 1),
        "dias_atras": 31,
        "dias_adelante": 366,
        "campo": "fecha",
        "aviso": {
            "titulo": "Tu SOAT vence pronto",
            "sujeto": "Tu SOAT",
            "cierre": "Renuévalo para evitar multas.",
        },
        "mensajes": {
            "vacia": "Pon la fecha de vencimiento del SOAT.",
            "invalida": "La fecha de vencimiento del SOAT no es válida.",
            "pasada": "Ese SOAT venció hace más de un mes. Si ya lo renovaste, pon la fecha del nuevo.",
            "futura": "Un SOAT dura un año: la fecha no puede estar a más de un año.",
        },
    },
    "tecno": {
        "recurrencia": "anual",
        "umbrales": (30, 15, 7, 1),
        "dias_atras": 31,
        "dias_adelante": 730,
        "campo": "fecha",
        "aviso": {
            "titulo": "Tu tecnomecánica vence pronto",
            "sujeto": "Tu tecnomecánica",
            "cierre": "Renuévala para evitar multas.",
        },
        "mensajes": {
            "vacia": "Pon la fecha de vencimiento de la tecnomecánica.",
            "invalida": "La fecha de vencimiento de la tecnomecánica no es válida.",
            "pasada": "Esa tecnomecánica venció hace más de un mes. Si ya la renovaste, pon la fecha de la nueva.",
            "futura": "La fecha no puede estar a más de dos años.",
        },
    },
}

TIPO_CREDITO = "credito"
# A dónde lleva tocar la notificación de una alerta.
URL_AVISO_ALERTA = "/mi-espacio"
# Alertas que van colgadas de una moto (una por tipo y moto).
TIPOS_POR_MOTO = ("soat", "tecno")

# El tope cuenta solo las de crédito: SOAT y tecno ya están acotadas a una
# por tipo y moto, y las motos tienen su propio tope.
MAX_ALERTAS_CREDITO = 20

MENSAJE_TOPE_ALERTAS = f"Puedes tener hasta {MAX_ALERTAS_CREDITO} alertas de crédito."
MENSAJE_ALERTA_NO_ENCONTRADA = "Esa alerta no existe o no es tuya."

# Errores de PostgREST (campo `code` de APIError) al escribir una alerta o
# un dispositivo. Lo que no está aquí cae en el genérico.
MENSAJES_ERROR_ALERTA = {
    "23514": "Alguno de los datos está fuera del rango permitido.",
    "42501": "No tienes permiso para hacer eso.",
    "PGRST301": "Tu sesión venció. Ingresa de nuevo.",
}
MENSAJE_ERROR_GENERICO = "No pudimos guardar el cambio. Intenta de nuevo en un momento."

# Al escribir la alerta de una moto: RLS (WITH CHECK) rechaza una moto
# ajena con 42501 y la FK una que no existe con 23503. Para el motero las
# dos son lo mismo: esa moto no es suya.
CODIGOS_MOTO_AJENA = ("42501", "23503")
# El índice único de la 024: otra petición creó la misma alerta antes.
CODIGO_DUPLICADA = "23505"

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


def es_tipo_por_moto(tipo) -> bool:
    return tipo in TIPOS_POR_MOTO


def rango_fecha(tipo: str, hoy: date = None):
    """(mínima, máxima) aceptadas para la fecha de ese tipo; el formulario las usa como min/max."""
    reglas = TIPOS_ALERTA_FECHA[tipo]
    hoy = hoy or _hoy()
    return (hoy - timedelta(days=reglas["dias_atras"]),
            hoy + timedelta(days=reglas["dias_adelante"]))


def rango_fecha_credito(hoy: date = None):
    return rango_fecha(TIPO_CREDITO, hoy)


def validar_fecha_alerta(tipo: str, valor) -> date:
    """Valida la fecha de una alerta de ese tipo (ISO, dentro de su rango) o lanza ErrorValidacion."""
    reglas = TIPOS_ALERTA_FECHA[tipo]
    campo, mensajes = reglas["campo"], reglas["mensajes"]
    if valor in (None, ""):
        raise ErrorValidacion(mensajes["vacia"], campo)
    if not isinstance(valor, str):
        raise ErrorValidacion(mensajes["invalida"], campo)
    try:
        fecha = date.fromisoformat(valor.strip())
    except ValueError:
        raise ErrorValidacion(mensajes["invalida"], campo)

    minima, maxima = rango_fecha(tipo)
    if fecha < minima:
        raise ErrorValidacion(mensajes["pasada"], campo)
    if fecha > maxima:
        raise ErrorValidacion(mensajes["futura"], campo)
    return fecha


def _fila_alerta(tipo: str, fecha: date) -> dict:
    reglas = TIPOS_ALERTA_FECHA[tipo]
    return {
        "tipo": tipo,
        "modo": "fecha",
        "recurrencia": reglas["recurrencia"],
        "fecha_objetivo": fecha.isoformat(),
        "umbrales_dias": list(reglas["umbrales"]),
    }


def validar_alerta_credito(form) -> dict:
    """
    Valida el formulario de la alerta de crédito (solo `fecha_cuota`) y
    devuelve la fila a insertar, sin usuario_id (lo pone la ruta desde la
    sesión). Tipo, modo, recurrencia y umbrales los fija el servidor:
    aunque el formulario los mande, se ignoran.
    """
    campo = TIPOS_ALERTA_FECHA[TIPO_CREDITO]["campo"]
    return _fila_alerta(TIPO_CREDITO, validar_fecha_alerta(TIPO_CREDITO, form.get(campo)))


def validar_alerta_moto(tipo: str, moto_id: int, form) -> dict:
    """
    Valida el formulario de la alerta de SOAT o tecno de una moto (solo
    `fecha`) y devuelve la fila a insertar, sin usuario_id. Que la moto
    sea del motero no se decide aquí: lo exige el WITH CHECK de RLS.
    """
    if not es_tipo_por_moto(tipo):
        raise ValueError(f"Tipo de alerta por moto desconocido: {tipo}")
    campo = TIPOS_ALERTA_FECHA[tipo]["campo"]
    fecha = validar_fecha_alerta(tipo, form.get(campo))
    return {**_fila_alerta(tipo, fecha), "moto_usuario_id": moto_id}


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


def separar_alertas(alertas):
    """
    Reparte las alertas (ya pasadas por para_mostrar) entre la lista
    general y las tarjetas de las motos:
    (sin_moto, {moto_id: {tipo: alerta}}).
    """
    sin_moto, por_moto = [], {}
    for a in alertas:
        moto_id = a.get("moto_usuario_id")
        if moto_id is None:
            sin_moto.append(a)
        else:
            por_moto.setdefault(moto_id, {})[a.get("tipo")] = a
    return sin_moto, por_moto


def _como_fecha(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(valor)


def avisos_a_enviar(alertas, hoy: date, ya_enviados) -> list:
    """
    Decide qué avisos de alertas salen hoy. Función pura, sin I/O.

    Por cada alerta activa en modo 'fecha':
      - ocurrencia = proxima_ocurrencia(ancla, recurrencia, hoy): la fecha
        de este ciclo (hoy o después). Sin ocurrencia (una alerta sin
        recurrencia que ya pasó) no hay aviso.
      - dias = ocurrencia - hoy; el umbral es el más chico de los
        `umbrales_dias` de la fila que sea >= dias ("bucket"). Hace de
        catch-up: si el job no corrió el día 30, el aviso de 30 sale el 29;
        y una vez enviado no se repite.
      - ciclo = la ocurrencia en ISO. Se saltea si (alerta_id, ciclo,
        umbral) está en ya_enviados; el ciclo siguiente vuelve a avisar.

    Devuelve [(alerta_id, ciclo, umbral, dias, ocurrencia), ...].
    """
    avisos = []
    for a in alertas:
        if not a.get("activo", True) or a.get("modo") != "fecha":
            continue
        ancla = _como_fecha(a.get("fecha_objetivo"))
        umbrales = sorted(a.get("umbrales_dias") or [])
        if ancla is None or not umbrales:
            continue
        ocurrencia = proxima_ocurrencia(ancla, a.get("recurrencia") or "ninguna", hoy)
        if ocurrencia is None:
            continue
        dias = (ocurrencia - hoy).days
        umbral = next((u for u in umbrales if u >= dias), None)
        if umbral is None:
            continue
        ciclo = ocurrencia.isoformat()
        if (a["id"], ciclo, umbral) in ya_enviados:
            continue
        avisos.append((a["id"], ciclo, umbral, dias, ocurrencia))
    return avisos


def texto_aviso_alerta(tipo: str, ocurrencia: date, dias: int) -> dict:
    """Título y cuerpo de la notificación de una alerta, según su tipo (TIPOS_ALERTA_FECHA)."""
    aviso = TIPOS_ALERTA_FECHA[tipo]["aviso"]
    if dias == 0:
        cuando = "vence hoy"
    elif dias == 1:
        cuando = "vence mañana"
    else:
        cuando = f"vence en {dias} días"
    return {
        "titulo": aviso["titulo"],
        "cuerpo": f"{aviso['sujeto']} {cuando} ({fecha_legible(ocurrencia)}). {aviso['cierre']}",
    }

"""
Módulo de contratos.

Fase 1 — captura de datos desde el RUNT: el encargado de sede pega el
texto de la consulta RUNT en el detalle de la moto; parsear_runt() lo
organiza en columnas y se guarda en datos_contrato (un registro por moto).

Fase 2 — contrato de venta en Word: generar_contrato() cruza la venta,
el comprador, los pagos y los datos_contrato de la moto, y llena la
plantilla app/plantillas/contrato.docx. No se guarda el .docx: se
regenera de los datos cada vez que hace falta.

SEGURIDAD - AISLAMIENTO POR SEDE:
Igual que gastos y detalle_ventas: el panel usa get_supabase_admin(),
que SALTA RLS. El aislamiento vive aquí, reutilizando _sede_del_alcance
para no tener dos reglas distintas de "quién ve qué sede".

FIDELIDAD AL RUNT:
Los valores se guardan tal cual vienen (solo se recortan espacios). Nada
de convertir números ni fechas: el contrato debe decir exactamente lo
que dice el registro oficial.
"""

import unicodedata
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from docxtpl import DocxTemplate

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios.detalle_ventas import _sede_del_alcance, TODAS_LAS_SEDES, venta_en_alcance

# Tope del texto pegado: una consulta RUNT completa ocupa unos pocos KB.
# Evita que alguien mande un blob enorme al parser.
MAX_CARACTERES_RUNT = 20000

# Etiqueta RUNT (normalizada: sin tildes, mayúsculas, sin ':' final)
# -> columna de datos_contrato. Se aceptan variantes que aparecen en
# distintas versiones de la consulta.
MAPA_RUNT = {
    "PLACA DEL VEHICULO": "placa",
    "PLACA": "placa",
    "NRO. DE LICENCIA DE TRANSITO": "licencia_transito",
    "NRO DE LICENCIA DE TRANSITO": "licencia_transito",
    "NUMERO DE LICENCIA DE TRANSITO": "licencia_transito",
    "LICENCIA DE TRANSITO": "licencia_transito",
    "AUTORIDAD DE TRANSITO": "autoridad_transito",
    "ESTADO DEL VEHICULO": "estado_vehiculo",
    "TIPO DE SERVICIO": "tipo_servicio",
    "CLASE DE VEHICULO": "clase_vehiculo",
    "MARCA": "marca",
    "LINEA": "linea",
    "MODELO": "modelo",
    "COLOR": "color",
    "NUMERO DE SERIE": "numero_serie",
    "NUMERO DE MOTOR": "numero_motor",
    "NUMERO DE CHASIS": "numero_chasis",
    "NUMERO DE VIN": "numero_vin",
    "CILINDRAJE": "cilindraje",
    "TIPO DE CARROCERIA": "tipo_carroceria",
    "TIPO CARROCERIA": "tipo_carroceria",
    "TIPO DE COMBUSTIBLE": "tipo_combustible",
    "TIPO COMBUSTIBLE": "tipo_combustible",
    "FECHA DE MATRICULA INICIAL": "fecha_matricula",
    "FECHA DE MATRICULA": "fecha_matricula",
}

# Columnas de datos_contrato, en el orden del RUNT (para la interfaz).
COLUMNAS = list(dict.fromkeys(MAPA_RUNT.values()))

ETIQUETAS_VISIBLES = {
    "placa": "Placa",
    "licencia_transito": "Licencia de tránsito",
    "autoridad_transito": "Autoridad de tránsito",
    "estado_vehiculo": "Estado del vehículo",
    "tipo_servicio": "Tipo de servicio",
    "clase_vehiculo": "Clase de vehículo",
    "marca": "Marca",
    "linea": "Línea",
    "modelo": "Modelo",
    "color": "Color",
    "numero_serie": "Número de serie",
    "numero_motor": "Número de motor",
    "numero_chasis": "Número de chasis",
    "numero_vin": "Número VIN",
    "cilindraje": "Cilindraje",
    "tipo_carroceria": "Tipo de carrocería",
    "tipo_combustible": "Tipo de combustible",
    "fecha_matricula": "Fecha de matrícula",
}


def _normalizar_etiqueta(linea: str) -> str:
    """
    Lleva una línea a la forma de las claves de MAPA_RUNT: sin tildes,
    mayúsculas, espacios colapsados, sin ':' final y sin sufijos entre
    paréntesis como '(DD/MM/AAAA)'.
    """
    texto = unicodedata.normalize("NFKD", linea)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    if "(" in texto:
        texto = texto.split("(", 1)[0]
    texto = " ".join(texto.upper().split())
    return texto.rstrip(":").strip()


def parsear_runt(texto: str) -> dict:
    """
    Convierte el texto pegado del RUNT en {columna: valor}, solo con
    los campos encontrados.

    Formato principal: la etiqueta en una línea y el valor en la línea
    siguiente. Si la línea siguiente es OTRA etiqueta, el dato está
    ausente en el RUNT (pasa, por ejemplo, con el VIN): se salta ese
    campo sin consumir la etiqueta siguiente.

    También acepta 'ETIQUETA: valor' en la misma línea. Si una etiqueta
    aparece dos veces, gana la primera (la sección de datos del
    vehículo va antes que SOAT/RTM en la consulta).
    """
    lineas = [l.strip() for l in (texto or "").splitlines()]
    lineas = [l for l in lineas if l]

    datos = {}
    for i, linea in enumerate(lineas):
        columna = MAPA_RUNT.get(_normalizar_etiqueta(linea))
        valor = None

        if columna:
            if i + 1 < len(lineas):
                siguiente = lineas[i + 1]
                if _normalizar_etiqueta(siguiente) not in MAPA_RUNT:
                    valor = siguiente
        elif ":" in linea:
            etiqueta, resto = linea.split(":", 1)
            columna = MAPA_RUNT.get(_normalizar_etiqueta(etiqueta))
            valor = resto.strip() or None

        if columna and valor and columna not in datos:
            datos[columna] = valor

    return datos


def moto_en_alcance(moto_id: int):
    """
    Devuelve la moto si el usuario en sesión puede cargar/ver sus datos
    de contrato según su sede, o None (no existe, o es de otra sede).
    Es la muralla de escritura: el id viene de la URL y se puede editar.
    """
    alcance = _sede_del_alcance()
    if alcance is None:
        return None  # usuario mal configurado: no opera nada

    moto = repositorios.obtener_moto_por_id(moto_id)
    if not moto:
        return None

    if alcance is TODAS_LAS_SEDES:
        return moto

    if moto.get("sede_id") == alcance:
        return moto
    return None


def obtener_datos(moto_id: int):
    """Datos de contrato ya cargados de una moto, o None. La ruta ya validó el alcance."""
    return repositorios.obtener_datos_contrato(moto_id)


def _placa_comparable(placa) -> str:
    return "".join((placa or "").upper().split()).replace("-", "")


def procesar_y_guardar(moto_id: int, texto_runt: str) -> dict:
    """
    Valida alcance, parsea el texto del RUNT y guarda (upsert) los datos
    de contrato de la moto. Devuelve lo que se guardó. Lanza
    ErrorValidacion si algo falla.
    """
    moto = moto_en_alcance(moto_id)
    if not moto:
        raise ErrorValidacion("La moto no existe o no pertenece a su sede.", "moto")

    texto_runt = (texto_runt or "").strip()
    if not texto_runt:
        raise ErrorValidacion("Pegue el texto de la consulta RUNT.", "texto_runt")
    if len(texto_runt) > MAX_CARACTERES_RUNT:
        raise ErrorValidacion("El texto pegado es demasiado largo para una consulta RUNT.",
                              "texto_runt")

    datos = parsear_runt(texto_runt)
    if not datos:
        raise ErrorValidacion(
            "No se reconoció ningún dato del RUNT. Verifique que pegó la consulta completa.",
            "texto_runt")

    # Protección contra pegar el RUNT de OTRA moto: el contrato saldría
    # con los datos equivocados. Solo se compara si ambos tienen placa.
    placa_runt = _placa_comparable(datos.get("placa"))
    placa_moto = _placa_comparable(moto.get("placa"))
    if placa_runt and placa_moto and placa_runt != placa_moto:
        raise ErrorValidacion(
            f"La placa del RUNT ({datos['placa']}) no coincide con la de esta moto "
            f"({moto['placa']}).", "texto_runt")

    # Registro completo: los campos que no vinieron quedan en NULL, así
    # una re-carga reemplaza todo y no deja valores viejos mezclados.
    registro = {columna: datos.get(columna) for columna in COLUMNAS}
    return repositorios.guardar_datos_contrato(moto["id"], registro)


# ============================================================
# FASE 2 — CONTRATO DE VENTA EN WORD
# ============================================================

# Colombia no tiene horario de verano: UTC-5 fijo. El servidor (Railway)
# corre en UTC; sin esto, un contrato hecho después de las 7 p.m. saldría
# con la fecha de mañana.
HORA_COLOMBIA = timezone(timedelta(hours=-5))

PLANTILLA_CONTRATO = Path(__file__).resolve().parent.parent / "plantillas" / "contrato.docx"

# Nombres internos (los de detalle_ventas) -> texto presentable en el
# contrato. Si aparece un valor que no está aquí, se muestra tal cual
# en vez de romper la generación.
METODOS_PRESENTABLES = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "financiado": "Financiado",
    "permuta": "Permuta",
}
ENTIDADES_PRESENTABLES = {
    "banco_bogota": "Banco de Bogotá",
    "vanti": "Vanti",
    "addi": "Addi",
    "sistecredito": "Sistecrédito",
}

# Obligatorios que bloquean la generación: sin ellos el contrato no
# identifica el vehículo o al comprador.
OBLIGATORIOS_VEHICULO = {
    "placa": "la placa",
    "numero_chasis": "el número de chasis",
    "numero_motor": "el número de motor",
}


def _formatear_pesos(valor) -> str:
    """8500000 -> '8.500.000'. Misma lógica que el filtro 'pesos' de las plantillas."""
    if valor is None:
        return ""
    return f"{valor:,.0f}".replace(",", ".")


def _linea_de_pago(pago: dict) -> str:
    metodo = pago.get("metodo") or ""
    texto = METODOS_PRESENTABLES.get(metodo, metodo)
    if metodo == "financiado":
        entidad = pago.get("entidad") or ""
        texto += f" ({ENTIDADES_PRESENTABLES.get(entidad, entidad)})"
    return texto


def generar_contrato(venta_id: int):
    """
    Genera el contrato de venta en Word para una venta completa.
    Devuelve (BytesIO con el .docx, nombre_de_archivo). Lanza
    ErrorValidacion si la venta no está en el alcance del usuario o si
    falta algún dato obligatorio (indicando cuál).
    """
    venta = venta_en_alcance(venta_id)
    if not venta:
        raise ErrorValidacion("La venta no existe o no pertenece a su sede.", "venta")

    if venta.get("estado") and venta["estado"] != "activa":
        raise ErrorValidacion("No se puede generar contrato de una venta anulada.", "venta")

    if not venta.get("detalle_completo") or not venta.get("comprador_id"):
        raise ErrorValidacion(
            "La venta no tiene el detalle cargado (comprador, pagos y precio).", "venta")

    datos = repositorios.obtener_datos_contrato(venta["moto_id"]) if venta.get("moto_id") else None
    if not datos:
        raise ErrorValidacion(
            "Faltan los datos del RUNT de esta moto, cárguelos primero.", "datos_contrato")

    faltantes = [nombre for campo, nombre in OBLIGATORIOS_VEHICULO.items()
                 if not (datos.get(campo) or "").strip()]

    comprador = repositorios.obtener_comprador_por_id(venta["comprador_id"]) or {}
    if not (comprador.get("nombre") or "").strip():
        faltantes.append("el nombre del comprador")
    if not (comprador.get("cedula") or "").strip():
        faltantes.append("la cédula del comprador")

    if faltantes:
        raise ErrorValidacion(
            "No se puede generar el contrato. Falta: " + ", ".join(faltantes) + ".",
            "datos_contrato")

    pagos = [
        {"linea": _linea_de_pago(p), "monto": _formatear_pesos(p.get("monto"))}
        for p in repositorios.obtener_pagos_de_venta(venta_id)
    ]

    contexto = {
        "fecha": datetime.now(HORA_COLOMBIA).strftime("%d/%m/%Y"),
        "comprador": comprador["nombre"].strip(),
        "cedula": comprador["cedula"].strip(),
        "telefono": comprador.get("telefono") or "",
        "placa": datos.get("placa") or "",
        "clase": datos.get("clase_vehiculo") or "",
        "marca": datos.get("marca") or "",
        "linea": datos.get("linea") or "",
        "modelo": datos.get("modelo") or "",
        "color": datos.get("color") or "",
        "autoridad": datos.get("autoridad_transito") or "",
        "tarjeta": datos.get("licencia_transito") or "",
        "chasis": datos.get("numero_chasis") or "",
        "motor": datos.get("numero_motor") or "",
        "serie": datos.get("numero_serie") or "",
        "precio": _formatear_pesos(venta.get("precio_venta")),
        "traspaso": _formatear_pesos(venta.get("valor_traspaso")),
        "pagos": pagos,
    }

    # autoescape: los valores vienen del RUNT y del formulario; un '&' o
    # '<' sin escapar corrompería el XML del .docx.
    documento = DocxTemplate(str(PLANTILLA_CONTRATO))
    documento.render(contexto, autoescape=True)

    salida = BytesIO()
    documento.save(salida)
    salida.seek(0)

    placa_archivo = "".join(c for c in contexto["placa"] if c.isalnum()) or f"venta{venta_id}"
    return salida, f"contrato_{placa_archivo}.docx"

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

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from docxtpl import DocxTemplate
from flask import current_app

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
    # No salen del RUNT (por eso no están en MAPA_RUNT ni en COLUMNAS):
    # se cargan a mano en el registro de compra, solo motos importadas.
    # Tampoco los toca una re-carga del RUNT (procesar_y_guardar solo
    # escribe COLUMNAS).
    "manifiesto_aduana": "Manifiesto de aduana",
    "fecha_manifiesto": "Fecha del manifiesto",
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


def parsear_texto_runt(texto_runt) -> dict:
    """
    Valida el texto pegado (no vacío, tamaño acotado) y lo parsea.
    Devuelve {columna: valor}. Lanza ErrorValidacion si no hay texto o
    no se reconoce ningún dato.
    """
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
    return datos


def moto_desde_runt(datos_runt: dict) -> dict:
    """
    Traduce datos del RUNT (salida de parsear_runt) a campos de motos,
    para prellenar el formulario de compra. Lo que no se pueda traducir
    queda en None: el formulario lo muestra vacío y validar_datos_moto
    lo exige al registrar.

    OJO con el cruce de nombres: en el RUNT, LINEA es lo que en motos
    llamamos 'modelo' (ej: "FZ 2.0"), y MODELO es el AÑO del vehículo
    (ej: "2019"). Por eso modelo <- linea y anio <- modelo.
    """
    def _entero(texto):
        coincidencia = re.search(r"\d+", texto or "")
        return int(coincidencia.group()) if coincidencia else None

    return {
        "marca": datos_runt.get("marca"),
        "modelo": datos_runt.get("linea"),
        "anio": _entero(datos_runt.get("modelo")),
        "color": datos_runt.get("color"),
        "placa": datos_runt.get("placa"),
        # El RUNT trae el cilindraje como texto ("150", "149.00 CC"):
        # se toma el primer número entero.
        "cilindraje": _entero(datos_runt.get("cilindraje")),
    }


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

    datos = parsear_texto_runt(texto_runt)

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
# FASE 2 — CONTRATOS EN WORD (VENTA Y COMPRA)
# ============================================================

# Hora de Colombia (America/Bogota): UTC-5 fijo, sin horario de verano
# desde 1993. Offset fijo en vez de ZoneInfo("America/Bogota") porque
# ZoneInfo necesita la base de zonas del sistema o el paquete tzdata,
# que en Windows no viene y en el contenedor no está garantizada.
HORA_COLOMBIA = timezone(timedelta(hours=-5))

CARPETA_PLANTILLAS = Path(__file__).resolve().parent.parent / "plantillas"
PLANTILLA_CONTRATO = CARPETA_PLANTILLAS / "contrato.docx"
PLANTILLA_CONTRATO_COMPRA = CARPETA_PLANTILLAS / "contrato_compra.docx"

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
# identifica el vehículo.
OBLIGATORIOS_VEHICULO = {
    "placa": "la placa",
    "numero_chasis": "el número de chasis",
    "numero_motor": "el número de motor",
}


def fecha_operacion(created_at) -> str:
    """
    Fecha de una operación (created_at de Supabase, ISO en UTC) en hora
    de Colombia, como dd/mm/aaaa. Los contratos SIEMPRE usan esta fecha,
    no la del día en que se generan: regenerarlos no puede cambiarla.
    Ojo: una operación de las 9 p.m. en Bogotá ya es "mañana" en UTC.
    """
    if not created_at:
        return ""
    momento = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(HORA_COLOMBIA).strftime("%d/%m/%Y")


def _formatear_pesos(valor) -> str:
    """8500000 -> '8.500.000'. Misma lógica que el filtro 'pesos' de las plantillas."""
    if valor is None:
        return ""
    return f"{valor:,.0f}".replace(",", ".")


def _pesos_si_hay(valor) -> str:
    """Como _formatear_pesos, pero 0 o None -> "": en la plantilla, un
    monto vacío es falso y permite {% if traspaso_comprador %}."""
    return _formatear_pesos(valor) if valor else ""


def _linea_de_pago(pago: dict) -> str:
    metodo = pago.get("metodo") or ""
    texto = METODOS_PRESENTABLES.get(metodo, metodo)
    if metodo == "financiado":
        entidad = pago.get("entidad") or ""
        texto += f" ({ENTIDADES_PRESENTABLES.get(entidad, entidad)})"
    return texto


def _linea_de_pago_compra(pago: dict, metodos_compra: dict) -> str:
    """
    Método legible y, si los tiene, entidad y descripción, separados por
    guion: "Cancelación prenda - Banco de Bogotá".
    """
    metodo = pago.get("metodo") or ""
    partes = [metodos_compra.get(metodo, {}).get("etiqueta")
              or METODOS_PRESENTABLES.get(metodo, metodo)]
    entidad = pago.get("entidad")
    if entidad:
        partes.append(ENTIDADES_PRESENTABLES.get(entidad, entidad))
    if pago.get("descripcion"):
        partes.append(pago["descripcion"].strip())
    return " - ".join(p for p in partes if p)


def _datos_vehiculo(moto_id):
    """
    Datos del RUNT de la moto y la lista de obligatorios del vehículo
    que faltan. Lanza ErrorValidacion si la moto no tiene RUNT cargado.
    """
    datos = repositorios.obtener_datos_contrato(moto_id) if moto_id else None
    if not datos:
        raise ErrorValidacion(
            "Faltan los datos del RUNT de esta moto, cárguelos primero.", "datos_contrato")
    faltantes = [nombre for campo, nombre in OBLIGATORIOS_VEHICULO.items()
                 if not (datos.get(campo) or "").strip()]
    return datos, faltantes


def _contexto_vehiculo(datos: dict) -> dict:
    """Marcadores del vehículo, comunes a los dos contratos."""
    return {
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
    }


def _bloquear_si_falta(faltantes: list):
    if faltantes:
        raise ErrorValidacion(
            "No se puede generar el contrato. Falta: " + ", ".join(faltantes) + ".",
            "datos_contrato")


def _renderizar(plantilla: Path, contexto: dict, respaldo: str):
    """
    Llena la plantilla. Devuelve (BytesIO con el .docx, placa para el
    nombre del archivo, o 'respaldo' si no hay placa).
    """
    # autoescape: los valores vienen del RUNT y del formulario; un '&' o
    # '<' sin escapar corrompería el XML del .docx.
    documento = DocxTemplate(str(plantilla))
    documento.render(contexto, autoescape=True)

    salida = BytesIO()
    documento.save(salida)
    salida.seek(0)

    placa_archivo = "".join(c for c in contexto["placa"] if c.isalnum()) or respaldo
    return salida, placa_archivo


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

    datos, faltantes = _datos_vehiculo(venta.get("moto_id"))

    comprador = repositorios.obtener_persona_por_id(venta["comprador_id"]) or {}
    if not (comprador.get("nombre") or "").strip():
        faltantes.append("el nombre del comprador")
    if not (comprador.get("cedula") or "").strip():
        faltantes.append("la cédula del comprador")

    _bloquear_si_falta(faltantes)

    pagos = [
        {"linea": _linea_de_pago(p), "monto": _formatear_pesos(p.get("monto"))}
        for p in repositorios.obtener_pagos_de_venta(venta_id)
    ]

    # Ventas anteriores a la migración 014 sin traspaso: None -> 0.
    valor_traspaso = venta.get("valor_traspaso") or 0
    traspaso_comprador = venta.get("traspaso_comprador") or 0

    contexto = {
        "fecha": fecha_operacion(venta.get("created_at")),
        "nit": current_app.config["NIT"],
        "comprador": comprador["nombre"].strip(),
        "cedula": comprador["cedula"].strip(),
        "telefono": comprador.get("telefono") or "",
        **_contexto_vehiculo(datos),
        "precio": _formatear_pesos(venta.get("precio_venta")),
        # Vacíos cuando son 0, para los {% if %} de las cláusulas 2 y 6.
        "traspaso_total": _pesos_si_hay(valor_traspaso),
        "traspaso_comprador": _pesos_si_hay(traspaso_comprador),
        "traspaso_empresa": _pesos_si_hay(valor_traspaso - traspaso_comprador),
        "caso_traspaso": caso_traspaso(valor_traspaso, traspaso_comprador, "comprador"),
        "pagos": pagos,
    }

    salida, placa = _renderizar(PLANTILLA_CONTRATO, contexto, f"venta{venta_id}")
    return salida, f"contrato_{placa}.docx"


def caso_traspaso(valor_traspaso: int, parte_contraparte: int,
                  contraparte: str = "vendedor") -> str:
    """
    Quién asume el traspaso, para que la plantilla elija el texto de la
    cláusula. contraparte es el particular de la operación: 'vendedor'
    en una compra, 'comprador' en una venta. Devuelve:
    - contraparte: la asume toda (o el traspaso vale 0);
    - 'empresa': la contraparte no pone nada;
    - 'compartido': cada uno una parte.
    """
    if parte_contraparte == valor_traspaso:
        return contraparte
    if parte_contraparte == 0:
        return "empresa"
    return "compartido"


def generar_contrato_compra(compra_id: int):
    """
    Genera el contrato de compra en Word: compra + vendedor (personas)
    + datos_contrato + pagos. Devuelve (BytesIO, nombre_de_archivo).
    Lanza ErrorValidacion si la compra no está en el alcance del usuario
    o si falta algún obligatorio (indicando cuál).
    """
    # Import diferido: compras importa contratos (e inventario, que a su
    # vez importa contratos); arriba sería un import circular.
    from app.servicios import compras

    compra = compras.compra_en_alcance(compra_id)
    if not compra:
        raise ErrorValidacion("La compra no existe o no pertenece a su sede.", "compra")

    # Las compras históricas (antes del registro con RUNT) no tienen
    # vendedor ni traspaso: no hay de dónde sacar el contrato.
    if not compra.get("vendedor_id") or compra.get("valor_traspaso") is None:
        raise ErrorValidacion(
            "Esta compra es anterior al registro con contrato: no tiene vendedor "
            "ni traspaso cargados.", "compra")

    datos, faltantes = _datos_vehiculo(compra.get("moto_id"))

    vendedor = repositorios.obtener_persona_por_id(compra["vendedor_id"]) or {}
    if not (vendedor.get("nombre") or "").strip():
        faltantes.append("el nombre del vendedor")
    if not (vendedor.get("cedula") or "").strip():
        faltantes.append("la cédula del vendedor")
    if not (vendedor.get("telefono") or "").strip():
        faltantes.append("el teléfono del vendedor")
    if not (compra.get("propietario_registrado") or "").strip():
        faltantes.append("el propietario registrado")
    if not compra.get("precio_compra"):
        faltantes.append("el precio de compra")

    _bloquear_si_falta(faltantes)

    valor_traspaso = compra["valor_traspaso"]
    traspaso_vendedor = compra.get("traspaso_vendedor") or 0

    pagos = [
        {"linea": _linea_de_pago_compra(p, compras.METODOS_PAGO_COMPRA),
         "monto": _formatear_pesos(p.get("monto"))}
        for p in repositorios.obtener_pagos_de_compra(compra_id)
    ]

    contexto = {
        "fecha": fecha_operacion(compra.get("created_at")),
        "nit": current_app.config["NIT"],
        "vendedor": vendedor["nombre"].strip(),
        "cedula": vendedor["cedula"].strip(),
        "telefono": vendedor["telefono"].strip(),
        **_contexto_vehiculo(datos),
        "propietario": compra["propietario_registrado"].strip(),
        "manifiesto": datos.get("manifiesto_aduana") or "",
        "fecha_manifiesto": datos.get("fecha_manifiesto") or "",
        "precio": _formatear_pesos(compra["precio_compra"]),
        "traspaso_vendedor": _formatear_pesos(traspaso_vendedor),
        "traspaso_total": _formatear_pesos(valor_traspaso),
        "traspaso_empresa": _formatear_pesos(valor_traspaso - traspaso_vendedor),
        "caso_traspaso": caso_traspaso(valor_traspaso, traspaso_vendedor),
        "pagos": pagos,
    }

    salida, placa = _renderizar(PLANTILLA_CONTRATO_COMPRA, contexto, f"compra{compra_id}")
    return salida, f"contrato_compra_{placa}.docx"

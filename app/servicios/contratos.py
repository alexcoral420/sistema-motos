"""
Módulo de contratos — Fase 1: captura de datos desde el RUNT.

El encargado de sede pega el texto de la consulta RUNT en el detalle
de la moto; parsear_runt() lo organiza en columnas y se guarda en
datos_contrato (un registro por moto). La Fase 2 (generar el Word)
es aparte y solo lee de esa tabla.

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
from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios.detalle_ventas import _sede_del_alcance, TODAS_LAS_SEDES

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

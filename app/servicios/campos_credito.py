# app/servicios/campos_credito.py
#
# FUENTE UNICA DE VERDAD sobre que datos le pedimos al cliente.
#
# Antes esta informacion estaba repartida en tres lugares (el prompt del
# asistente, el prompt del extractor y la validacion), y agregar un campo
# obligaba a tocar los tres. Aqui se declara UNA vez y las tres piezas se
# generan desde esta lista.
#
# Para agregar o quitar un dato, se edita SOLO este archivo.

import re


# ============================================================
# LA DEFINICION
# ============================================================
#
# Claves de cada campo:
#   clave        Nombre interno. Es la clave del JSON del extractor.
#   etiqueta     Como lo nombramos ante el cliente y en el prompt.
#   tipo         Como se valida: texto | telefono_co | entero | si_no
#   obligatorio  Sin el no se guarda el lead.
#   sensible     Si es True, se guarda CIFRADO en la base.
#   activo       Si es False, el sistema entero lo ignora (no se pide,
#                no se extrae, no se valida). Sirve para dejar campos
#                preparados hasta que haya luz verde para usarlos.
#   columna      Columna de leads_chat donde se guarda. None = no se guarda.
#   maximo       Tope para campos numericos.

CAMPOS = [
    {
        "clave": "nombre",
        "etiqueta": "nombre",
        "tipo": "texto",
        "obligatorio": True,
        "sensible": False,
        "activo": True,
        "columna": "nombre",
    },
    {
        "clave": "telefono",
        "etiqueta": "número de WhatsApp",
        "tipo": "telefono_co",
        "obligatorio": True,
        "sensible": False,
        "activo": True,
        "columna": "telefono",
    },
    {
        "clave": "correo",
        "etiqueta": "correo electrónico",
        "tipo": "correo",
        "obligatorio": True,
        "sensible": False,
        "activo": True,
        "columna": "correo",
    },

    {
        "clave": "valor_financiar",
        "etiqueta": "monto que quiere financiar",
        "tipo": "entero",
        "obligatorio": False,
        "sensible": False,
        "activo": True,
        "columna": "valor_financiar",
        "maximo": 100_000_000,
    },
    {
        "clave": "cuota_inicial",
        "etiqueta": "cuota inicial",
        "tipo": "entero",
        "obligatorio": False,
        "sensible": False,
        "activo": True,
        "columna": "cuota_inicial",
        "maximo": 100_000_000,
    },
    {
        "clave": "plazo_meses",
        "etiqueta": "plazo en meses",
        "tipo": "entero",
        "obligatorio": False,
        "sensible": False,
        "activo": True,
        "columna": "plazo_meses",
        "maximo": 120,
    },
    {
        "clave": "cuota_calculada",
        "etiqueta": "cuota mensual calculada",
        "tipo": "entero",
        "obligatorio": False,
        "sensible": False,
        "activo": True,
        "columna": "cuota_calculada",
        "maximo": 100_000_000,
    },

    # ----- Preparados, APAGADOS hasta tener asesoria legal -----
    # Son datos financieros regulados por la Ley 1266. La infraestructura
    # (columna cifrada, validacion, consentimiento reforzado) ya existe;
    # solo falta poner "activo": True cuando corresponda.
    {
        "clave": "ingresos",
        "etiqueta": "ingresos mensuales aproximados",
        "tipo": "entero",
        "obligatorio": False,
        "sensible": True,
        "activo": False,
        "columna": "ingresos_cifrado",
        "maximo": 500_000_000,
    },
    {
        "clave": "reportado",
        "etiqueta": "si está reportado en centrales de riesgo",
        "tipo": "si_no",
        "obligatorio": False,
        "sensible": True,
        "activo": False,
        "columna": "reportado_cifrado",
    },
    {
        "clave": "vida_crediticia",
        "etiqueta": "si tiene historial crediticio",
        "tipo": "si_no",
        "obligatorio": False,
        "sensible": True,
        "activo": False,
        "columna": "vida_crediticia_cifrado",
    },
]


# ============================================================
# CONSULTAS SOBRE LA DEFINICION
# ============================================================

def campos_activos():
    """Los campos que el sistema usa hoy."""
    return [c for c in CAMPOS if c.get("activo")]


def campos_obligatorios():
    """Sin estos no se guarda un lead."""
    return [c for c in campos_activos() if c.get("obligatorio")]


def campos_sensibles():
    """Los que van cifrados en la base."""
    return [c for c in campos_activos() if c.get("sensible")]


# ============================================================
# GENERADORES PARA LAS TRES PIEZAS
# ============================================================

def instruccion_para_prompt():
    """
    Texto que se inserta en el system prompt del asistente para decirle
    que datos debe conseguir. Se arma desde la definicion, asi que si un
    campo se apaga, el asistente deja de pedirlo automaticamente.
    """
    obligatorios = [c["etiqueta"] for c in campos_obligatorios()]
    opcionales = [
        c["etiqueta"] for c in campos_activos()
        if not c.get("obligatorio")
    ]

    texto = "DATOS QUE DEBES CONSEGUIR DEL CLIENTE:\n"
    texto += "- Imprescindibles (sin estos un asesor no puede contactarlo): "
    texto += ", ".join(obligatorios) + ".\n"
    if opcionales:
        texto += "- Utiles si surgen naturalmente en la charla: "
        texto += ", ".join(opcionales) + ".\n"
    texto += "- No pidas ningun otro dato personal que no este en esta lista."
    return texto


def esquema_para_extractor():
    """
    Descripcion de las claves del JSON que debe devolver el extractor.
    Se genera desde la definicion para que nunca se desincronice con
    lo que el asistente pide ni con lo que la validacion espera.
    """
    tipos_json = {
        "texto": "string o null",
        "telefono_co": "string o null",
        "correo": "string o null",
        "entero": "numero entero o null",
        "si_no": '"si" o "no" o null',
    }

    lineas = []
    for c in campos_activos():
        lineas.append(f'  "{c["clave"]}": {tipos_json.get(c["tipo"], "string o null")},')
    lineas.append('  "autorizo": true o false')
    return "{\n" + "\n".join(lineas) + "\n}"


# ============================================================
# VALIDACION
# ============================================================

def _validar_texto(valor, maximo=80):
    if not isinstance(valor, str):
        return None
    limpio = valor.strip()
    if len(limpio) < 2 or len(limpio) > maximo:
        return None
    return limpio


def _validar_telefono_co(valor):
    """Celular colombiano: 10 digitos empezando por 3."""
    if not valor:
        return None
    limpio = re.sub(r"[^0-9]", "", str(valor))
    if limpio.startswith("57") and len(limpio) == 12:
        limpio = limpio[2:]
    if len(limpio) == 10 and limpio.startswith("3"):
        return limpio
    return None

def _validar_correo(valor):
    """
    Validacion basica de correo: algo@algo.algo, sin espacios.
    No pretende cubrir todos los casos del estandar; alcanza para
    descartar lo que claramente no es un correo.
    """
    if not isinstance(valor, str):
        return None
    limpio = valor.strip().lower()
    if len(limpio) > 120:
        return None
    if re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", limpio):
        return limpio
    return None


def _validar_entero(valor, maximo):
    if isinstance(valor, bool):
        return None
    if not isinstance(valor, int):
        return None
    if valor < 0 or valor > maximo:
        return None
    return valor


def _validar_si_no(valor):
    if not isinstance(valor, str):
        return None
    limpio = valor.strip().lower()
    if limpio in ("si", "sí", "true", "yes"):
        return "si"
    if limpio in ("no", "false"):
        return "no"
    return None


def validar(datos):
    """
    Valida los datos crudos que reporto el extractor.

    Devuelve (limpios, faltantes):
      limpios   dict solo con los campos activos que pasaron validacion
      faltantes lista de etiquetas de los obligatorios que no llegaron

    Lo que no pase la validacion simplemente no entra: preferimos guardar
    un lead con menos datos que uno con datos inventados o mal formados.
    """
    datos = datos or {}
    limpios = {}
    faltantes = []

    for campo in campos_activos():
        crudo = datos.get(campo["clave"])
        tipo = campo["tipo"]

        if tipo == "texto":
            valor = _validar_texto(crudo)
        elif tipo == "telefono_co":
            valor = _validar_telefono_co(crudo)
        elif tipo == "correo":
            valor = _validar_correo(crudo)
        elif tipo == "entero":
            valor = _validar_entero(crudo, campo.get("maximo", 100_000_000))
        elif tipo == "si_no":
            valor = _validar_si_no(crudo)
        else:
            valor = None

        if valor is not None:
            limpios[campo["clave"]] = valor
        elif campo.get("obligatorio"):
            faltantes.append(campo["etiqueta"])

    return limpios, faltantes


# ============================================================
# MAPEO A LA BASE DE DATOS
# ============================================================

def a_columnas(limpios, cifrar):
    """
    Convierte los datos validados en el dict de columnas de leads_chat.

    'cifrar' es la funcion de cifrado. Los campos marcados como sensibles
    se cifran automaticamente: la decision de que es sensible se declara
    una sola vez, en CAMPOS, y aqui se obedece.
    """
    registro = {}
    for campo in campos_activos():
        columna = campo.get("columna")
        if not columna:
            continue
        valor = limpios.get(campo["clave"])
        if valor is None:
            continue
        registro[columna] = cifrar(str(valor)) if campo.get("sensible") else valor
    return registro
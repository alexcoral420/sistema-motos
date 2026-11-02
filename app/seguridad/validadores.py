"""
Validadores centralizados de entrada externa (vulnerabilidad #6).

Regla madre: NUNCA confíes en la entrada externa. Todo dato que llega
de fuera (formularios, mensajes, webhooks) se valida ANTES de usarlo.

Enfoque LISTA BLANCA: definimos qué es válido y rechazamos todo lo
demás. Más seguro que intentar enumerar lo que es malo (siempre se
escapa algo).

Cada validador NO revienta ante datos malos: devuelve un resultado
controlado. Usamos una excepción propia (ErrorValidacion) que las rutas
capturan para responder con un mensaje limpio, sin exponer tracebacks.

Este módulo es NEUTRAL: no importa la base, ni clientes de Supabase, ni
servicios. Lo usan tanto el panel como el blueprint del motero, que tiene
prohibido arrastrar el cliente service_role (tests/test_cuentas_motero.py).
"""

import re

# Placa de moto en Colombia: 3 letras + 2 números + 1 letra (ABC12D). Las
# más viejas no traen la letra final (ABC12).
PATRON_PLACA_MOTO = re.compile(r"^[A-Z]{3}[0-9]{2}[A-Z]?$")

class ErrorValidacion(Exception):
    """
    Error de validación de una entrada.

    Se lanza cuando un dato no cumple las reglas. Lleva un mensaje
    apto para mostrar al usuario (sin detalles internos) y, opcional,
    el nombre del campo que falló.

    Las rutas capturan esta excepción y responden con el mensaje,
    en vez de dejar que un error técnico escape hacia afuera.
    """
    def __init__(self, mensaje: str, campo: str = None):
        self.mensaje = mensaje
        self.campo = campo
        super().__init__(mensaje)


def validar_texto(valor, campo: str, min_len: int = 1, max_len: int = 200,
                  obligatorio: bool = True):
    """
    Valida un campo de texto.

    - Comprueba que sea texto (str).
    - Recorta espacios de los extremos.
    - Verifica longitud mínima y máxima.
    - Si obligatorio=False y el valor está vacío, devuelve None (válido).

    Devuelve el texto ya limpio (sin espacios sobrantes) si es válido.
    Lanza ErrorValidacion si no cumple.
    """
    # Si no vino nada (None) y no es obligatorio, es válido como "vacío".
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorValidacion(f"El campo '{campo}' es obligatorio.", campo)
        return None

    # Debe ser texto. Si llega otro tipo, es entrada malformada.
    if not isinstance(valor, str):
        raise ErrorValidacion(f"El campo '{campo}' tiene un formato inválido.", campo)

    # Quitamos espacios de los extremos: "  Yamaha  " -> "Yamaha".
    valor = valor.strip()

    # Tras recortar, puede quedar vacío (eran solo espacios).
    if not valor:
        if obligatorio:
            raise ErrorValidacion(f"El campo '{campo}' es obligatorio.", campo)
        return None

    # Longitud dentro del rango permitido.
    if len(valor) < min_len:
        raise ErrorValidacion(
            f"El campo '{campo}' debe tener al menos {min_len} caracteres.", campo)
    if len(valor) > max_len:
        raise ErrorValidacion(
            f"El campo '{campo}' no puede superar los {max_len} caracteres.", campo)

    return valor


def validar_entero(valor, campo: str, minimo: int = None, maximo: int = None,
                   obligatorio: bool = True):
    """
    Valida y convierte un campo numérico entero.

    - Acepta un número o un texto que represente un entero ("2022").
    - Verifica rango mínimo/máximo si se indican.
    - Si obligatorio=False y viene vacío, devuelve None.

    Devuelve el entero convertido si es válido. Lanza ErrorValidacion
    si no es un número o está fuera de rango.
    """
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorValidacion(f"El campo '{campo}' es obligatorio.", campo)
        return None

    # Intentamos convertir a entero. Si falla, no era un número.
    try:
        numero = int(valor)
    except (ValueError, TypeError):
        raise ErrorValidacion(f"El campo '{campo}' debe ser un número entero.", campo)

    if minimo is not None and numero < minimo:
        raise ErrorValidacion(
            f"El campo '{campo}' no puede ser menor que {minimo}.", campo)
    if maximo is not None and numero > maximo:
        raise ErrorValidacion(
            f"El campo '{campo}' no puede ser mayor que {maximo}.", campo)

    return numero


def validar_opcion(valor, campo: str, opciones_validas: list,
                   obligatorio: bool = True):
    """
    Valida que un valor sea UNA de las opciones permitidas (lista blanca pura).

    Ejemplo: el estado de una moto solo puede ser disponible/reservado/vendido.
    Cualquier otro valor se rechaza.

    Devuelve el valor si está en la lista. Lanza ErrorValidacion si no.
    """
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorValidacion(f"El campo '{campo}' es obligatorio.", campo)
        return None

    if valor not in opciones_validas:
        raise ErrorValidacion(
            f"El campo '{campo}' tiene un valor no permitido.", campo)

    return valor


def validar_telefono(valor, campo: str = "número"):
    """
    Valida un número de teléfono de forma básica (para el webhook).

    Acepta solo dígitos y un '+' inicial opcional, con longitud razonable.
    No verifica que el número exista de verdad; solo su forma, para
    rechazar basura evidente antes de procesar un mensaje.

    Devuelve el número limpio si es válido. Lanza ErrorValidacion si no.
    """
    if not valor or not isinstance(valor, str):
        raise ErrorValidacion("Número de teléfono inválido.", campo)

    numero = valor.strip()

    # Permitimos un '+' inicial; el resto deben ser dígitos.
    sin_mas = numero[1:] if numero.startswith("+") else numero
    if not sin_mas.isdigit():
        raise ErrorValidacion("Número de teléfono inválido.", campo)

    # Rango de longitud razonable para teléfonos internacionales.
    if not (7 <= len(sin_mas) <= 15):
        raise ErrorValidacion("Número de teléfono inválido.", campo)

    return numero


def validar_placa_moto(valor, campo: str = "placa", obligatorio: bool = False):
    """
    Valida una placa de moto colombiana (ABC12D o ABC12).

    Tolera espacios, guiones y minúsculas ("abc-12d" -> "ABC12D"). Si viene
    vacía y no es obligatoria, devuelve None.

    Devuelve la placa normalizada. Lanza ErrorValidacion si no tiene forma
    de placa de moto.
    """
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorValidacion("La placa es obligatoria.", campo)
        return None
    if not isinstance(valor, str):
        raise ErrorValidacion("La placa no es válida.", campo)

    placa = re.sub(r"[\s-]", "", valor).upper()
    if not placa:
        if obligatorio:
            raise ErrorValidacion("La placa es obligatoria.", campo)
        return None
    if not PATRON_PLACA_MOTO.match(placa):
        raise ErrorValidacion("La placa debe tener el formato ABC12D.", campo)
    return placa
"""
Servicio del simulador de financiación.

Calcula cuotas de crédito con el sistema de amortización francés (cuota
fija mensual) y registra los leads de personas interesadas.

IMPORTANTE: este simulador es orientativo. NO decide aprobación de
crédito ni consulta centrales de riesgo. Solo calcula cuotas estimadas
y captura el interés del cliente para que un asesor lo contacte. La
decisión crediticia real la toma la entidad financiera aliada.
"""

from app.db import repositorios


# Parámetros del crédito (los define la financiera aliada).
TASA_ANUAL = 0.1025          # 10.25% anual
PLAZOS = [6, 12, 24, 48]     # meses ofrecidos


class ErrorSimulador(Exception):
    """Error de validación en el simulador."""
    def __init__(self, mensaje):
        self.mensaje = mensaje
        super().__init__(mensaje)


def calcular_cuota(monto, meses, tasa_anual=TASA_ANUAL):
    """
    Calcula la cuota mensual fija (sistema de amortización francés).

    Fórmula: cuota = P * [i(1+i)^n] / [(1+i)^n - 1]
      P = monto a financiar
      i = tasa mensual (anual / 12)
      n = número de meses

    Devuelve la cuota mensual redondeada a pesos enteros.
    """
    if monto <= 0 or meses <= 0:
        return 0

    i = tasa_anual / 12          # tasa mensual
    factor = (1 + i) ** meses    # (1+i)^n, se usa dos veces
    cuota = monto * (i * factor) / (factor - 1)
    return round(cuota)


def simular(valor_moto, cuota_inicial=0):
    """
    Simula el crédito para los cuatro plazos.

    Devuelve el monto a financiar y una lista con la cuota, el total y
    los intereses de cada plazo. No registra nada: solo calcula.
    """
    # Validaciones: viene de entrada del usuario, no confiamos.
    if not isinstance(valor_moto, int) or valor_moto <= 0:
        raise ErrorSimulador("El valor de la moto debe ser un número positivo.")

    if not isinstance(cuota_inicial, int) or cuota_inicial < 0:
        raise ErrorSimulador("La cuota inicial no puede ser negativa.")

    if cuota_inicial >= valor_moto:
        raise ErrorSimulador("La cuota inicial no puede ser mayor o igual al valor de la moto.")

    monto = valor_moto - cuota_inicial

    resultados = []
    for meses in PLAZOS:
        cuota = calcular_cuota(monto, meses)
        total = cuota * meses
        intereses = total - monto
        resultados.append({
            "meses": meses,
            "cuota": cuota,
            "total": total,
            "intereses": intereses,
        })

    return {
        "monto_financiar": monto,
        "valor_moto": valor_moto,
        "cuota_inicial": cuota_inicial,
        "planes": resultados,
    }


def registrar_lead(nombre, telefono, correo, valor_financiar,
                   cuota_inicial=0, moto_id=None, autorizo=False):
    """
    Registra un lead de financiación, con el consentimiento del usuario.

    NO registra si la persona no autorizó el tratamiento de datos: el
    consentimiento es obligatorio (Ley 1581 de Habeas Data).
    """
    # El consentimiento es condición legal para guardar datos personales.
    if not autorizo:
        raise ErrorSimulador("Debe autorizar el tratamiento de datos para continuar.")

    # Validaciones de los datos personales.
    if not nombre or not isinstance(nombre, str):
        raise ErrorSimulador("El nombre es obligatorio.")
    if not telefono or not isinstance(telefono, str):
        raise ErrorSimulador("El teléfono es obligatorio.")
    if not correo or "@" not in correo:
        raise ErrorSimulador("Un correo válido es obligatorio.")

    repositorios.registrar_lead_financiacion(
        nombre=nombre.strip(),
        telefono=telefono.strip(),
        correo=correo.strip(),
        valor_financiar=valor_financiar,
        cuota_inicial=cuota_inicial,
        moto_id=moto_id,
        autorizo=autorizo,
    )
"""
Servicio de compras: el encargado de sede registra una moto que la
empresa le compra a un particular.

Flujo: se pega la consulta RUNT, se revisa el formulario prellenado y
se registra. La función de Postgres registrar_compra (migración 013)
crea moto, datos de contrato, compra, pagos y gasto de traspaso en una
sola transacción. Aquí se valida todo ANTES de llamarla, para dar
mensajes claros; la función vuelve a proteger las reglas críticas.

DATOS DEL CONTRATO:
Salen SIEMPRE del parser del RUNT, re-parseando el texto que viaja en
el formulario. Nunca de campos sueltos del form: alguien podría editar
el HTML y poner otro número de motor. La única excepción es el
manifiesto de aduana, que no está en el RUNT y se carga a mano.

SEGURIDAD - SEDE Y ASESOR:
La sede sale del alcance de la sesión (_sede_del_alcance). El asesor
viene del form, así que se revalida contra la base: existe, es asesor,
está activo y es de la sede de la compra.
"""

import re

from app.db import repositorios
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.servicios import contratos, inventario, personas, sedes
from app.servicios.detalle_ventas import _sede_del_alcance, TODAS_LAS_SEDES

# Métodos de pago de una compra: fuente única para validación y para el
# formulario. Al vendedor: se le entrega la plata. A terceros: parte del
# precio se usa para pagar algo a nombre del vendedor (levantar la
# prenda, un comparendo, impuestos atrasados); exigen descripción.
METODOS_PAGO_COMPRA = {
    "efectivo": {"etiqueta": "Efectivo", "a_tercero": False},
    "transferencia": {"etiqueta": "Transferencia", "a_tercero": False},
    "prenda": {"etiqueta": "Prenda", "a_tercero": True},
    "comparendo": {"etiqueta": "Comparendo", "a_tercero": True},
    "impuesto": {"etiqueta": "Impuesto", "a_tercero": True},
    "otro": {"etiqueta": "Otro", "a_tercero": True},
}

MAX_MONTO = 999999999


# ============================================================
#  APOYO AL FORMULARIO
# ============================================================

def contexto_formulario() -> dict:
    """
    Lo que el formulario necesita según el alcance del usuario:
    - sede_fija: la sede del encargado (no se elige), o None.
    - sedes: lista para elegir (solo gerencia/admin).
    - asesores: los que se pueden elegir (de su sede, o todos con su
      sede_id para filtrar en pantalla). El servidor revalida igual.
    Lanza ErrorValidacion si el usuario no tiene sede válida.
    """
    alcance = _sede_del_alcance()
    if alcance is None:
        raise ErrorValidacion("Su usuario no tiene una sede asignada.", "sede")

    if alcance is TODAS_LAS_SEDES:
        return {
            "sede_fija": None,
            "sedes": sedes.listar_sedes(),
            "asesores": repositorios.listar_asesores_activos(),
        }
    return {
        "sede_fija": sedes.obtener_sede(alcance),
        "sedes": [],
        "asesores": repositorios.listar_asesores_activos(alcance),
    }


def pagos_del_form(form) -> list:
    """Filas de pago tal como llegan del form (sin validar), en orden."""
    return [
        {"metodo": m, "monto": mo, "descripcion": d}
        for m, mo, d in zip(form.getlist("pago_metodo"),
                            form.getlist("pago_monto"),
                            form.getlist("pago_descripcion"))
    ]


# ============================================================
#  VALIDACIONES
# ============================================================

def _sede_de_la_compra(form) -> int:
    """Encargado -> su sede. Gerencia/admin -> la del form, si existe."""
    alcance = _sede_del_alcance()
    if alcance is None:
        raise ErrorValidacion("Su usuario no tiene una sede asignada.", "sede")
    if alcance is not TODAS_LAS_SEDES:
        return alcance

    sede_id = validadores.validar_entero(form.get("sede_id"), "sede", minimo=1)
    if str(sede_id) not in sedes.ids_validos():
        raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
    return sede_id


def _validar_asesor(asesor_id, sede_id: int) -> dict:
    asesor_id = validadores.validar_entero(asesor_id, "asesor", minimo=1)
    asesor = repositorios.obtener_usuario_por_id(asesor_id)
    if (not asesor
            or asesor.get("rol") != "asesor"
            or not asesor.get("activo")
            or asesor.get("sede_id") != sede_id):
        raise ErrorValidacion("El asesor elegido no es válido para esta sede.", "asesor")
    return asesor


def _validar_vendedor(form) -> dict:
    """Datos del vendedor limpios. El teléfono es obligatorio: va en el contrato."""
    telefono = re.sub(r"[\s-]", "", form.get("vendedor_telefono") or "")
    if not telefono:
        raise ErrorValidacion("El teléfono del vendedor es obligatorio.", "vendedor_telefono")
    correo = validadores.validar_texto(
        form.get("vendedor_correo"), "correo del vendedor", max_len=254, obligatorio=False)
    if correo and "@" not in correo:
        raise ErrorValidacion("El correo del vendedor no es válido.", "vendedor_correo")

    return {
        "nombre": validadores.validar_texto(
            form.get("vendedor_nombre"), "nombre del vendedor", min_len=3, max_len=120),
        # Se normaliza aquí para fallar antes de tocar la base.
        "cedula": personas.normalizar_cedula(form.get("vendedor_cedula")),
        "telefono": validadores.validar_telefono(telefono, "vendedor_telefono"),
        "correo": correo,
    }


def _validar_pagos(lista: list) -> list:
    pagos = []
    for p in lista:
        metodo = (p.get("metodo") or "").strip().lower()
        if metodo not in METODOS_PAGO_COMPRA:
            raise ErrorValidacion(f"Método de pago inválido: {metodo}", "pago")

        monto = validadores.validar_entero(p.get("monto"), "monto del pago",
                                           minimo=1, maximo=MAX_MONTO)

        descripcion = validadores.validar_texto(
            p.get("descripcion"), "descripción del pago", max_len=200, obligatorio=False)
        if METODOS_PAGO_COMPRA[metodo]["a_tercero"] and not descripcion:
            etiqueta = METODOS_PAGO_COMPRA[metodo]["etiqueta"]
            raise ErrorValidacion(
                f"El pago de {etiqueta.lower()} necesita una descripción "
                "(a quién se paga y la referencia).", "pago")

        pagos.append({"metodo": metodo, "monto": monto, "descripcion": descripcion})

    if not pagos:
        raise ErrorValidacion("Debe registrar al menos un pago.", "pago")
    return pagos


# ============================================================
#  REGISTRO
# ============================================================

def registrar_compra(form, sesion) -> dict:
    """
    Valida el formulario completo y registra la compra en una sola
    transacción. Devuelve {"moto_id", "compra_id"}. Lanza
    ErrorValidacion con un mensaje para el usuario si algo no cuadra
    (incluidos los rechazos de la función en la base).

    sesion: la sesión de Flask. Quién registra sale de aquí, nunca del form.
    """
    # 1. RUNT: los datos del contrato salen del parser, siempre.
    datos_runt = contratos.parsear_texto_runt(form.get("texto_runt"))

    # 2. Sede y moto. validar_datos_moto exige sede_id: se le pasa la
    #    sede ya decidida, no la que venga en el form.
    sede_id = _sede_de_la_compra(form)
    moto = inventario.validar_datos_moto(
        {**form.to_dict(), "sede_id": sede_id}, "por_publicar", exigir_precio=False)

    placa_runt = contratos._placa_comparable(datos_runt.get("placa"))
    if not placa_runt:
        raise ErrorValidacion("La consulta RUNT no trae la placa del vehículo.", "texto_runt")
    if contratos._placa_comparable(moto.get("placa")) != placa_runt:
        raise ErrorValidacion(
            f"La placa del formulario ({moto.get('placa') or 'vacía'}) no coincide con "
            f"la del RUNT ({datos_runt['placa']}).", "placa")

    datos_contrato = {columna: datos_runt.get(columna) for columna in contratos.COLUMNAS}
    datos_contrato["manifiesto_aduana"] = validadores.validar_texto(
        form.get("manifiesto_aduana"), "manifiesto de aduana", max_len=50, obligatorio=False)
    datos_contrato["fecha_manifiesto"] = validadores.validar_texto(
        form.get("fecha_manifiesto"), "fecha del manifiesto", max_len=20, obligatorio=False)

    # 3. Asesor y vendedor (validados; el vendedor se crea más abajo).
    asesor = _validar_asesor(form.get("asesor_id"), sede_id)
    vendedor = _validar_vendedor(form)

    # 4. Montos.
    precio_compra = validadores.validar_entero(
        form.get("precio_compra"), "precio de compra", minimo=1, maximo=MAX_MONTO)
    valor_traspaso = validadores.validar_entero(
        form.get("valor_traspaso"), "valor del traspaso", minimo=0, maximo=MAX_MONTO)
    traspaso_vendedor = validadores.validar_entero(
        form.get("traspaso_vendedor"), "traspaso que asume el vendedor",
        minimo=0, maximo=MAX_MONTO)
    if traspaso_vendedor > valor_traspaso:
        raise ErrorValidacion(
            "El traspaso que asume el vendedor no puede superar el valor total del traspaso.",
            "traspaso_vendedor")

    # 5. Pagos: deben sumar lo que efectivamente se paga.
    pagos = _validar_pagos(pagos_del_form(form))
    a_pagar = precio_compra - traspaso_vendedor
    suma = sum(p["monto"] for p in pagos)
    if suma != a_pagar:
        pesos = contratos._formatear_pesos
        raise ErrorValidacion(
            f"Los pagos suman ${pesos(suma)}, pero se deben pagar ${pesos(a_pagar)} "
            f"(precio ${pesos(precio_compra)} menos traspaso del vendedor "
            f"${pesos(traspaso_vendedor)}). Diferencia: ${pesos(abs(suma - a_pagar))}.",
            "pago")

    propietario = validadores.validar_texto(
        form.get("propietario_registrado"), "propietario registrado", min_len=3, max_len=120)

    # 6. Todo validado: recién ahora se toca la base.
    vendedor_id = personas.obtener_o_crear(vendedor)

    compra = {
        "sede_id": sede_id,
        "usuario_id": sesion.get("usuario_id"),
        "usuario_nombre": sesion.get("usuario_nombre"),
        "asesor_id": asesor["id"],
        "asesor_nombre": asesor.get("nombre_completo"),
        "vendedor_id": vendedor_id,
        "precio_compra": precio_compra,
        "valor_traspaso": valor_traspaso,
        "traspaso_vendedor": traspaso_vendedor,
        "propietario_registrado": propietario,
    }
    resultado = repositorios.registrar_compra_completa(moto, datos_contrato, compra, pagos)
    return {"moto_id": resultado["moto_id"], "compra_id": resultado["compra_id"]}

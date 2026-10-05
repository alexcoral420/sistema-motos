# servicios/detalle_ventas.py  (archivo nuevo)
"""
Módulo de detalle de ventas: el paso 2 que carga gerencia después de
la verificación (comprador, pagos, precio).

SEGURIDAD - AISLAMIENTO POR SEDE:
El panel usa get_supabase_admin(), que SALTA RLS. Por eso el aislamiento
por sede vive AQUÍ, en la app, y es la única muralla: si este filtro
falta en una consulta, no hay red debajo. Toda lectura de ventas del
módulo pasa por _sede_del_alcance().

Regla: fallar CERRADO. Un usuario mal configurado no ve nada, nunca
todo. El "ve todas las sedes" es explícito (solo gerencia/admin), no
un efecto colateral de un valor vacío.
"""

from flask import session
from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import personas

# Marcador explícito de "sin restricción de sede" (ve todas).
# Es un objeto único, imposible de confundir con un sede_id real ni
# con None. Que sea un valor propio y no None es a proposito: obliga
# a distinguir "ve todo" de "no se pudo determinar la sede".
TODAS_LAS_SEDES = object()


def _sede_del_alcance():
    """
    Decide qué sede puede ver el usuario en sesión. Tres resultados:

    - TODAS_LAS_SEDES  -> gerencia/admin: ve todas las sedes.
    - un sede_id (int) -> rol de sede: ve solo esa sede.
    - None             -> usuario mal configurado (rol de sede sin
                          sede asignada, o sin rol): NO VE NADA.

    La sede sale de la SESIÓN, nunca de un parámetro del request.
    """
    rol = session.get("rol")

    if rol in ("gerencia", "admin"):
        return TODAS_LAS_SEDES

    sede_id = session.get("sede_id")
    if sede_id is None:
        # Rol de sede sin sede: configuración inválida. Fallar cerrado.
        return None

    return sede_id


def listar_pendientes():
    """
    Ventas verificadas sin detalle, dentro del alcance del usuario.
    Si el usuario no tiene alcance válido, devuelve lista vacía.
    """
    alcance = _sede_del_alcance()

    if alcance is None:
        # Usuario mal configurado: no ve nada.
        return []

    if alcance is TODAS_LAS_SEDES:
        return repositorios.ventas_pendientes_detalle(sede_id=None)

    return repositorios.ventas_pendientes_detalle(sede_id=alcance)


def listar_ventas_de_mi_sede():
    """
    Todas las ventas (cualquier estado) dentro del alcance del usuario.
    Gerencia/admin ven todas; el encargado solo las de su sede.
    Si el usuario no tiene alcance válido, devuelve lista vacía.
    """
    alcance = _sede_del_alcance()

    if alcance is None:
        # Usuario mal configurado: no ve nada.
        return []

    if alcance is TODAS_LAS_SEDES:
        return repositorios.ventas_de_sede(sede_id=None)

    return repositorios.ventas_de_sede(sede_id=alcance)

def venta_en_alcance(venta_id):
    """
    Devuelve la venta si el usuario en sesión puede operarla según su
    alcance de sede, o None si no (fuera de su sede, o no existe).

    Es la muralla de ESCRITURA: sin esto, un encargado podría cargar
    detalle a una venta de otra sede mandando su id directo. La lectura
    (listar) ya filtra; esto protege el acceso a UNA venta puntual.
    """
    alcance = _sede_del_alcance()
    if alcance is None:
        return None  # usuario mal configurado: no opera nada

    venta = repositorios.obtener_venta_por_id(venta_id)
    if not venta:
        return None

    if alcance is TODAS_LAS_SEDES:
        return venta  # gerencia/admin: cualquier venta

    # Rol de sede: solo si la venta es de SU sede (la congelada en la venta)
    if venta.get("sede_id") == alcance:
        return venta
    return None


def comprador_de(venta: dict):
    """El comprador (persona) de una venta con detalle, o None."""
    if not venta.get("comprador_id"):
        return None
    return repositorios.obtener_persona_por_id(venta["comprador_id"])


# ============================================================
# VALIDACIÓN Y GUARDADO DEL DETALLE
# ============================================================

METODOS_VALIDOS = {"efectivo", "transferencia", "financiado", "permuta"}
ENTIDADES_VALIDAS = {"banco_bogota", "vanti", "addi", "sistecredito"}


def _validar_pago(metodo, entidad, monto):
    """Valida un pago. Levanta ErrorValidacion si algo no cuadra;
    devuelve el pago limpio si está bien."""
    metodo = (metodo or "").strip().lower()
    if metodo not in METODOS_VALIDOS:
        raise ErrorValidacion(f"Método de pago inválido: {metodo}", "pago")

    try:
        monto = int(monto)
    except (ValueError, TypeError):
        raise ErrorValidacion("Monto de pago inválido.", "pago")
    if monto <= 0:
        raise ErrorValidacion("El monto debe ser mayor a cero.", "pago")

    entidad_limpia = None
    if metodo == "financiado":
        entidad = (entidad or "").strip().lower()
        if entidad not in ENTIDADES_VALIDAS:
            raise ErrorValidacion("Falta la entidad financiera o no es válida.", "pago")
        entidad_limpia = entidad

    return {"metodo": metodo, "entidad": entidad_limpia, "monto": monto}


def _validar_monto_traspaso(valor, campo: str, etiqueta: str) -> int:
    """Entero >= 0, obligatorio (la función de la base no acepta nulos)."""
    texto = (str(valor) if valor is not None else "").strip()
    if not texto:
        raise ErrorValidacion(f"El {etiqueta} es obligatorio (0 si no aplica).", campo)
    try:
        numero = int(texto)
    except ValueError:
        raise ErrorValidacion(f"El {etiqueta} no es válido.", campo)
    if numero < 0:
        raise ErrorValidacion(f"El {etiqueta} no puede ser negativo.", campo)
    return numero


def _pesos(valor: int) -> str:
    """8500000 -> '8.500.000'."""
    return f"{valor:,}".replace(",", ".")


def guardar_detalle(venta_id, datos_comprador, lista_pagos, precio_venta,
                    valor_traspaso, traspaso_comprador, usuario_id):
    """
    Carga el detalle de una venta: comprador (reusa por cédula o crea),
    precio, traspaso (total y parte del comprador) y pagos.

    Aquí se valida todo (formatos, métodos, entidades, que los pagos
    sumen precio + traspaso del comprador) para dar mensajes claros
    ANTES de tocar la base. El guardado es UNA llamada a la función
    guardar_detalle_venta (migración 014): detalle, pagos y gasto de
    traspaso en una transacción. Si se vuelve a guardar, se reemplazan.

    La ruta ya validó con venta_en_alcance() que el usuario puede operar
    esta venta. usuario_id viene de la sesión. Lanza ErrorValidacion si
    algo no cuadra (incluidos los rechazos de la función en la base).
    """
    # 1. Precio y traspaso
    try:
        precio_venta = int(precio_venta)
    except (ValueError, TypeError):
        raise ErrorValidacion("Precio de venta inválido.", "precio_venta")
    if precio_venta <= 0:
        raise ErrorValidacion("El precio de venta debe ser mayor a cero.", "precio_venta")

    valor_traspaso = _validar_monto_traspaso(
        valor_traspaso, "valor_traspaso", "valor del traspaso")
    traspaso_comprador = _validar_monto_traspaso(
        traspaso_comprador, "traspaso_comprador", "traspaso que asume el comprador")
    if traspaso_comprador > valor_traspaso:
        raise ErrorValidacion(
            "El traspaso que asume el comprador no puede superar el valor total del traspaso.",
            "traspaso_comprador")

    # 2. Pagos
    pagos_limpios = [_validar_pago(p.get("metodo"), p.get("entidad"), p.get("monto"))
                     for p in lista_pagos]
    if not pagos_limpios:
        raise ErrorValidacion("Debe registrar al menos un pago.", "pago")

    # 3. La suma BLOQUEA: el comprador paga el precio más su parte del traspaso.
    a_pagar = precio_venta + traspaso_comprador
    suma = sum(p["monto"] for p in pagos_limpios)
    if suma != a_pagar:
        raise ErrorValidacion(
            f"Los pagos suman ${_pesos(suma)}, pero deben sumar ${_pesos(a_pagar)} "
            f"(precio ${_pesos(precio_venta)} más traspaso del comprador "
            f"${_pesos(traspaso_comprador)}). Diferencia: ${_pesos(abs(suma - a_pagar))}.",
            "pago")

    # 4. Todo validado: recién ahora se toca la base. La persona se reusa
    #    por cédula o se crea (sin actualizar si existe).
    comprador_id = personas.obtener_o_crear(datos_comprador)

    repositorios.guardar_detalle_venta_completo(
        venta_id, comprador_id, precio_venta, valor_traspaso, traspaso_comprador,
        pagos_limpios, usuario_id)

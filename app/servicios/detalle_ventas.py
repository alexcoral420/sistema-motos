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


def guardar_detalle(venta_id, datos_comprador, lista_pagos, precio_venta):
    """
    Carga el detalle de una venta: comprador (reusa por cédula o crea),
    pagos (validados), y marca la venta como completa.

    La ruta ya validó con venta_en_alcance() que el usuario puede operar
    esta venta. Aquí se asume ese chequeo hecho.

    Devuelve (ok, mensaje_error, aviso_suma).
    """
    # 1. Validar precio
    try:
        precio_venta = int(precio_venta)
    except (ValueError, TypeError):
        return False, "Precio de venta inválido.", None
    if precio_venta <= 0:
        return False, "El precio de venta debe ser mayor a cero.", None

        # 2. Validar todos los pagos
    pagos_limpios = []
    for p in lista_pagos:
        pagos_limpios.append(_validar_pago(p.get("metodo"), p.get("entidad"), p.get("monto")))

    if not pagos_limpios:
        raise ErrorValidacion("Debe registrar al menos un pago.", "pago")

    # 3. Aviso si la suma no cuadra (NO bloquea)
    suma = sum(p["monto"] for p in pagos_limpios)
    aviso_suma = None
    if suma != precio_venta:
        aviso_suma = (f"Los pagos suman ${suma:,} pero el precio es "
                      f"${precio_venta:,} (diferencia ${abs(suma - precio_venta):,}).")

    # 4. Comprador: reusar por cédula o crear (sin actualizar si existe)
    cedula = (datos_comprador.get("cedula") or "").strip()
    if not cedula:
        return False, "La cédula del comprador es obligatoria.", None

    existente = repositorios.buscar_comprador_por_cedula(cedula)
    if existente:
        comprador_id = existente["id"]
    else:
        nuevo = repositorios.crear_comprador({
            "nombre": (datos_comprador.get("nombre") or "").strip(),
            "cedula": cedula,
            "telefono": (datos_comprador.get("telefono") or "").strip() or None,
            "correo": (datos_comprador.get("correo") or "").strip() or None,
        })
        comprador_id = nuevo["id"]

    # 5. Insertar pagos. Borra los previos por si es reintento (anti-duplicado).
    for p in pagos_limpios:
        p["venta_id"] = venta_id
    repositorios.borrar_pagos_de_venta(venta_id)
    repositorios.insertar_pagos(pagos_limpios)

    # 6. Recién ahora marcar la venta como completa
    repositorios.completar_detalle_venta(venta_id, comprador_id, precio_venta)

    return True, None, aviso_suma
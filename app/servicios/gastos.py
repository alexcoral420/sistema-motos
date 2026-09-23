"""
Módulo de gastos: registra lo que cuesta cada moto (taller, repuestos,
lavadero) para poder calcular rentabilidad más adelante. Independiente
del módulo de ventas: no toca esas tablas ni su flujo.

SEGURIDAD - AISLAMIENTO POR SEDE:
Igual que detalle_ventas: el panel usa get_supabase_admin(), que SALTA
RLS. El aislamiento por sede vive aquí, reutilizando el mismo criterio
de alcance (_sede_del_alcance) que ya protege el módulo de ventas, para
no tener dos reglas distintas de "quién ve qué sede" en la misma app.

INTEGRACIÓN CON EL TALLER:
La llamada HTTP al taller es defensiva: va en try/except con timeout.
Si el taller no responde, el módulo sigue funcionando (gastos manuales
intactos) y solo avisa que la sincronización no se pudo hacer.
"""

import requests
from flask import current_app
from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios.detalle_ventas import _sede_del_alcance, TODAS_LAS_SEDES

TIPOS_MANUALES = {"repuesto", "lavadero"}


def moto_por_placa_en_alcance(placa: str):
    """
    Busca una moto por placa y valida que esté dentro del alcance de
    sede del usuario en sesión. Devuelve la moto o None (no existe, o
    es de otra sede: un encargado no puede cargar gastos ahí aunque
    escriba la placa correcta).
    """
    alcance = _sede_del_alcance()
    if alcance is None:
        return None

    placa = (placa or "").strip().upper()
    if not placa:
        return None

    moto = repositorios.obtener_moto_por_placa(placa)
    if not moto:
        return None

    if alcance is TODAS_LAS_SEDES:
        return moto

    if moto.get("sede_id") == alcance:
        return moto
    return None


def listar_gastos(moto_id: int):
    """Gastos de una moto y su total. La ruta ya validó el alcance."""
    gastos = repositorios.listar_gastos_de_moto(moto_id)
    total = sum(g["monto"] for g in gastos)
    return gastos, total


def crear_gasto_manual(placa: str, tipo: str, concepto: str, monto, fecha_gasto: str,
                        usuario_id: int):
    """
    Carga un gasto manual (repuesto o lavadero). Valida sede, tipo,
    monto y campos obligatorios. Lanza ErrorValidacion si algo falla.
    """
    moto = moto_por_placa_en_alcance(placa)
    if not moto:
        raise ErrorValidacion("La moto no existe o no pertenece a su sede.", "placa")

    if tipo not in TIPOS_MANUALES:
        raise ErrorValidacion("Tipo de gasto inválido.", "tipo")

    concepto = (concepto or "").strip()
    if not concepto:
        raise ErrorValidacion("El concepto es obligatorio.", "concepto")

    try:
        monto = int(monto)
    except (ValueError, TypeError):
        raise ErrorValidacion("El monto debe ser un número entero.", "monto")
    if monto <= 0:
        raise ErrorValidacion("El monto debe ser mayor a cero.", "monto")

    fecha_gasto = (fecha_gasto or "").strip()
    if not fecha_gasto:
        raise ErrorValidacion("La fecha del gasto es obligatoria.", "fecha_gasto")

    return repositorios.insertar_gasto({
        "moto_id": moto["id"],
        "placa": moto.get("placa"),
        "tipo": tipo,
        "concepto": concepto,
        "monto": monto,
        "fecha_gasto": fecha_gasto,
        "origen": "manual",
        "orden_taller": None,
        "usuario_id": usuario_id,
        "sede_id": moto.get("sede_id"),
    })


def _convertir_monto(valor) -> int:
    """Los montos del taller vienen como strings tipo '50000.00'."""
    return int(round(float(valor)))


def _llamar_taller(placa: str):
    """
    Consulta las órdenes del taller para una placa. Devuelve la lista
    de órdenes, o None si el taller no respondió (URL sin configurar,
    timeout, error de red o respuesta inválida). NUNCA rompe la página:
    quien llama debe tratar None como "no se pudo sincronizar".
    """
    taller_url = current_app.config.get("TALLER_URL")
    api_key = current_app.config.get("TALLER_API_KEY")
    if not taller_url or not api_key:
        return None

    try:
        respuesta = requests.get(
            f"{taller_url}/api/integracion/gasto-por-placa/{placa}",
            headers={"X-API-Key": api_key},
            timeout=8,
        )
        respuesta.raise_for_status()
        return respuesta.json().get("ordenes", [])
    except (requests.RequestException, ValueError):
        return None


def sincronizar_taller(placa: str):
    """
    Trae las órdenes del taller para una moto y guarda como gasto cada
    ítem de las órdenes que aún no estén registradas (anti-duplicado
    por orden_taller).

    Devuelve (cantidad_nuevas, aviso). aviso es None si todo salió
    bien; si el taller no respondió, cantidad_nuevas es 0 y aviso trae
    el mensaje para mostrar.
    """
    moto = moto_por_placa_en_alcance(placa)
    if not moto:
        raise ErrorValidacion("La moto no existe o no pertenece a su sede.", "placa")

    ordenes = _llamar_taller(moto["placa"])
    if ordenes is None:
        return 0, "El taller no respondió. Intente sincronizar de nuevo más tarde."

    ya_guardadas = repositorios.ordenes_taller_guardadas(moto["id"])

    gastos_nuevos = []
    for orden in ordenes:
        numero = orden.get("numero")
        if numero in ya_guardadas:
            continue  # anti-duplicado: esta orden ya se sincronizó antes

        for item in orden.get("items", []):
            gastos_nuevos.append({
                "moto_id": moto["id"],
                "placa": moto.get("placa"),
                "tipo": "taller",
                "concepto": item.get("descripcion"),
                "monto": _convertir_monto(item.get("subtotal", 0)),
                "fecha_gasto": orden.get("created_at"),
                "origen": "taller",
                "orden_taller": numero,
                "usuario_id": None,
                "sede_id": moto.get("sede_id"),
            })

    repositorios.insertar_gastos(gastos_nuevos)

    # Cuenta por ítem insertado, que es el grano fino que pidió el diseño.
    return len(gastos_nuevos), None

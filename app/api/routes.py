"""
API REST para sistemas externos (n8n).

Diferencias con los blueprints admin/publico:
  - Devuelve JSON, no HTML (la consume n8n, no un navegador).
  - Se autentica con API key (@requiere_api_key), no con sesión.
  - Solo expone lo mínimo: leer inventario y registrar intención.
  - Cada petición deja una línea en el log "auditoria.api" (ver
    registrar_peticion), también en producción.

Reutiliza los servicios existentes: no duplica lógica, solo la envuelve
en formato JSON para el consumo externo.
"""

import logging

from flask import Blueprint, current_app, g, request, jsonify
from app.auth.api_key import requiere_api_key, identificar_consumidor, CONSUMIDOR_PUBLICO
from app.seguridad.logging_config import obtener_logger, obtener_logger_api
from app.seguridad.limites import limiter
from app.servicios import inventario, catalogo, avaluo, recordatorios
from app.seguridad.validadores import ErrorValidacion
from app.db import repositorios
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.after_request
def registrar_peticion(respuesta):
    """
    Una línea de log por cada petición a /api, incluidos los rechazos
    (401, 429, 503): método, ruta, status, IP y consumidor.

    Sin datos personales: la ruta es la PLANTILLA de la regla
    (/api/motos/<int:moto_id>), nunca el query string (?q= puede traer
    una placa) ni el cuerpo. Del consumidor se registra la identidad que
    sale de la llave, jamás la llave.
    """
    consumidor = g.get("api_consumidor")
    if consumidor is None:
        # El decorador no llegó a correr: ruta pública, o un 429 del
        # rate limit que cortó antes en una ruta con llave.
        vista = current_app.view_functions.get(request.endpoint)
        consumidor = (identificar_consumidor() if getattr(vista, "requiere_api_key", False)
                      else CONSUMIDOR_PUBLICO)

    ruta = request.url_rule.rule if request.url_rule else "(sin ruta)"
    status = respuesta.status_code
    nivel = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
    obtener_logger_api().log(nivel, "API | %s %s | %s | ip=%s | consumidor=%s",
                             request.method, ruta, status, request.remote_addr, consumidor)
    return respuesta


@api_bp.route("/motos/buscar", methods=["GET"])
@requiere_api_key
def buscar_motos():
    """
    Busca motos disponibles según filtros.

    Filtros por query params (mismo contrato que el catálogo público):
        ?marca=BAJAJ&marca=YAMAHA   una o varias marcas
        ?cc=hasta-125               rango de cilindraje
        ?anio=2023-mas              rango de año
        ?precio=6-8m                rango de precio
        ?q=pulsar                   búsqueda por texto
        ?pagina=2                   página (15 por defecto)
        ?limite=100                 cuántas por página (máx 100)

    Usa el mismo servicio que el catálogo público: los filtros se validan
    igual y el orden es el mismo (popularidad reciente). No se duplica
    lógica, solo se envuelve en JSON.
    """
   

    resultado = catalogo.buscar_motos(request.args)

    return jsonify({
        "motos": resultado["motos"],
        "total": resultado["total_motos"],
        "pagina": resultado["pagina"],
        "total_paginas": resultado["total_paginas"],
    })

@api_bp.route("/motos/<int:moto_id>", methods=["GET"])
@requiere_api_key
def detalle_moto(moto_id):
    """Devuelve los datos de una moto específica por su id."""
    moto = inventario.obtener_moto(moto_id)
    if not moto:
        return jsonify({"error": "Moto no encontrada"}), 404
    return jsonify({"moto": moto})

@api_bp.route("/motos/todas", methods=["GET"])
@requiere_api_key
@limiter.limit("10 per day")
def todas_las_motos():
    """
    Devuelve el inventario disponible COMPLETO, sin paginar.

    Pensado para sincronizacion periodica: un sistema externo que mantiene
    su propia copia del catalogo. Para consultas puntuales conviene
    /api/motos/buscar, que filtra y pagina.

    Solo devuelve motos con estado 'disponible'. Una moto vendida deja de
    aparecer, y el sistema externo la retira de su copia en la siguiente
    sincronizacion.

    Limitado a 10 por dia: sincronizar es pesado y no tiene sentido
    repetirlo con frecuencia.
    """
    motos = inventario.listar_motos_disponibles()
    obtener_logger().info("API: sincronizacion completa, %s motos.", len(motos))
    return jsonify({
        "motos": motos,
        "total": len(motos),
    })
    
@api_bp.route("/intenciones", methods=["POST"])
@requiere_api_key
def registrar_intencion():
    """
    Registra una intención de compra (el cliente preguntó por una moto).

    Recibe JSON: { "moto_id": 12, "origen": "<id de la conversación>" }
    'origen' es opcional: identifica a quien pregunta para no contarlo dos
    veces (se guarda solo su HMAC). El dedup y los topes los decide el
    servicio (inventario.registrar_intencion_api).

    201 {"ok": true}                      registrada
    200 {"ok": true, "duplicada": true}   ya estaba; no se insertó
    429                                   se alcanzó un tope (moto o global)
    """
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        datos = {}
    moto_id = datos.get("moto_id")

    try:
        resultado = inventario.registrar_intencion_api(
            moto_id, datos.get("origen"), current_app.config.get("SECRET_KEY"))
    except ErrorValidacion as e:
        return jsonify({"error": e.mensaje}), 400
    except inventario.TopeIntencionesSuperado as e:
        obtener_logger_api().warning(
            "API: tope de intenciones superado (%s), moto %s.", e.alcance, moto_id)
        return jsonify({"error": "Demasiadas intenciones registradas. Intenta más tarde."}), 429

    if resultado is None:
        return jsonify({"error": "La moto no existe"}), 404
    if resultado == inventario.INTENCION_DUPLICADA:
        return jsonify({"ok": True, "duplicada": True}), 200
    return jsonify({"ok": True}), 201


@api_bp.route("/avaluo", methods=["GET"])
@limiter.limit("30 per hour")
def avaluo_moto():
    """
    Estima el valor de una moto: ?marca=&modelo=&anio=&km=

    Pública (sin API key) a propósito: la usa la página /simula-compra
    desde el navegador, donde una llave quedaría expuesta. Solo devuelve
    agregados (percentiles y conteo), y el rate limit acota el abuso.
    """
    try:
        consulta = avaluo.validar_consulta(request.args)
    except ErrorValidacion as e:
        return jsonify({"error": e.mensaje}), 400
    return jsonify(avaluo.avaluo(**consulta))


@api_bp.route("/recordatorios", methods=["POST"])
@limiter.limit("10 per hour")
def crear_recordatorio():
    """
    Activa un recordatorio push de vencimiento (SOAT / tecnomecánica).

    Pública (sin API key) como /avaluo: la llama la página
    /recordatorio-soat desde el navegador. Escribe en la base, por eso su
    rate limit es más estricto. Devuelve el token del recordatorio (el
    dispositivo lo guarda para editarlo o borrarlo después).
    """
    try:
        token = recordatorios.crear(request.get_json(silent=True))
    except ErrorValidacion as e:
        return jsonify({"error": e.mensaje}), 400
    return jsonify({"token": token}), 201

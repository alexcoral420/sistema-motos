"""
API REST para sistemas externos (webhook de n8n).

Diferencias con los blueprints admin/publico:
  - Devuelve JSON, no HTML (la consume n8n, no un navegador).
  - Se autentica con API key (@requiere_api_key), no con sesión.
  - Solo expone lo mínimo: leer inventario y registrar intención.

Reutiliza los servicios existentes: no duplica lógica, solo la envuelve
en formato JSON para el consumo externo.
"""

from flask import Blueprint, request, jsonify

from app.servicios import busqueda, inventario
from app.auth.api_key import requiere_api_key
from app.seguridad.logging_config import obtener_logger
from app.servicios import busqueda, inventario, metricas
from app.servicios.metricas import ErrorMetrica
api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/motos/buscar", methods=["GET"])
@requiere_api_key
def buscar_motos():
    """
    Busca motos disponibles según filtros.
    Los filtros llegan como query params: ?marca=yamaha&precio_max=8000000
    Reutiliza el mismo servicio que el catálogo público.
    """
    resultado = busqueda.buscar(request.args)
    # busqueda.buscar devuelve un dict con las motos y metadatos.
    # Para la API, devolvemos la lista de motos en JSON.
    return jsonify({
        "motos": resultado.get("motos", []),
        "total": len(resultado.get("motos", [])),
    })

@api_bp.route("/motos/<int:moto_id>", methods=["GET"])
@requiere_api_key
def detalle_moto(moto_id):
    """Devuelve los datos de una moto específica por su id."""
    moto = inventario.obtener_moto(moto_id)
    if not moto:
        return jsonify({"error": "Moto no encontrada"}), 404
    return jsonify({"moto": moto})

@api_bp.route("/intenciones", methods=["POST"])
@requiere_api_key
def registrar_intencion():
    """
    Registra una intención de compra (el cliente preguntó por una moto).
    Recibe JSON: { "moto_id": 12 }
    Reutiliza el mismo servicio que el botón web.
    """
    datos = request.get_json(silent=True) or {}
    moto_id = datos.get("moto_id")

    # Validar que vino un moto_id y que es un entero.
    if not isinstance(moto_id, int):
        return jsonify({"error": "moto_id es obligatorio y debe ser un número"}), 400

    # Confirmar que la moto existe antes de registrar.
    if not inventario.obtener_moto(moto_id):
        return jsonify({"error": "La moto no existe"}), 404

    inventario.registrar_intencion(moto_id)
    obtener_logger().info("API: intención registrada para moto %s.", moto_id)

    return jsonify({"ok": True}), 201

@api_bp.route("/mensajes", methods=["POST"])
@requiere_api_key
def registrar_mensaje():
    """
    Registra un mensaje del webhook con sus métricas.
    Recibe JSON:
      {
        "telefono": "573001112233",   (obligatorio)
        "canal": "whatsapp",           (opcional, default whatsapp)
        "nivel": 1,                    (obligatorio: 0, 1 o 2)
        "tokens_entrada": 120,         (opcional, default 0)
        "tokens_salida": 45,           (opcional, default 0)
        "modelo": "modelo-x",          (opcional)
        "moto_id": 12                  (opcional)
      }
    Resuelve contacto y conversación (regla de 24h) y guarda el mensaje.
    """
    datos = request.get_json(silent=True) or {}

    try:
        conversacion_id = metricas.registrar_mensaje(
            telefono=datos.get("telefono"),
            canal=datos.get("canal"),
            nivel=datos.get("nivel"),
            tokens_entrada=datos.get("tokens_entrada", 0),
            tokens_salida=datos.get("tokens_salida", 0),
            modelo=datos.get("modelo"),
            moto_id=datos.get("moto_id"),
        )
    except ErrorMetrica as e:
        return jsonify({"error": e.mensaje}), 400

    return jsonify({"ok": True, "conversacion_id": conversacion_id}), 201
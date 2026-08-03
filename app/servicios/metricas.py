"""
Servicio de métricas del webhook.

Orquesta el registro de un mensaje entrante: resuelve a qué contacto y a
qué conversación pertenece (buscando o creando según haga falta), inserta
el mensaje con sus métricas, y refresca la ventana de actividad.

La regla de las 24h vive aquí: si el contacto no tiene una conversación
activa (último mensaje hace menos de 24h), se abre una nueva. Así, alguien
que vuelve a escribir tras días o semanas inicia una conversación distinta.
"""

from app.db import repositorios


class ErrorMetrica(Exception):
    """Error de validación al registrar una métrica."""
    def __init__(self, mensaje):
        self.mensaje = mensaje
        super().__init__(mensaje)


def registrar_mensaje(telefono, canal, nivel,
                      tokens_entrada=0, tokens_salida=0,
                      modelo=None, moto_id=None):
    """
    Registra un mensaje del webhook, resolviendo contacto y conversación.

    Flujo:
      1. Buscar el contacto por teléfono; si no existe, crearlo.
      2. Buscar su conversación activa (< 24h); si no hay, abrir una nueva.
      3. Insertar el mensaje con sus métricas.
      4. Refrescar el ultimo_mensaje de la conversación.

    Devuelve el id de la conversación (útil para enlazar una venta después).
    """
    # --- Validaciones: viene de afuera, no confiamos ---
    if not telefono or not isinstance(telefono, str):
        raise ErrorMetrica("El teléfono es obligatorio.")

    if not isinstance(nivel, int) or nivel not in (0, 1, 2):
        raise ErrorMetrica("El nivel debe ser 0, 1 o 2.")

    if not isinstance(tokens_entrada, int) or tokens_entrada < 0:
        raise ErrorMetrica("tokens_entrada debe ser un entero no negativo.")

    if not isinstance(tokens_salida, int) or tokens_salida < 0:
        raise ErrorMetrica("tokens_salida debe ser un entero no negativo.")

    canal = canal or "whatsapp"

    # --- 1. Contacto: buscar o crear ---
    contacto = repositorios.buscar_contacto_por_telefono(telefono)
    if not contacto:
        contacto = repositorios.crear_contacto(telefono, canal)

    # --- 2. Conversación activa (< 24h) o nueva ---
    conversacion = repositorios.buscar_conversacion_activa(contacto["id"])
    if not conversacion:
        conversacion = repositorios.crear_conversacion(contacto["id"], canal, moto_id)

    # --- 3. Insertar el mensaje con sus métricas ---
    repositorios.insertar_mensaje(
        conversacion["id"], nivel, tokens_entrada, tokens_salida, modelo)

    # --- 4. Refrescar la ventana de actividad ---
    repositorios.actualizar_ultimo_mensaje(conversacion["id"])

    return conversacion["id"]
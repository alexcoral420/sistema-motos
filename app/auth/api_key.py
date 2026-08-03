"""
Autenticación por API key para la API del webhook.
"""

import os
import secrets
from functools import wraps
from flask import request, jsonify


def requiere_api_key(func):
    """Exige una API key válida en el header Authorization: Bearer <key>."""
    @wraps(func)
    def envoltura(*args, **kwargs):
        clave_esperada = os.environ.get("API_WEBHOOK_KEY")

        if not clave_esperada:
            return jsonify({"error": "API no configurada"}), 503

        cabecera = request.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer "):
            return jsonify({"error": "Falta autenticación"}), 401

        clave_recibida = cabecera[7:]

        if not secrets.compare_digest(clave_recibida, clave_esperada):
            return jsonify({"error": "Autenticación inválida"}), 401

        return func(*args, **kwargs)
    return envoltura
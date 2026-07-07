"""
Blueprint público: rutas que cualquiera puede ver, sin login.
Aquí vivirán /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.

Qué es un Blueprint:
En el app.py viejo, TODAS las rutas colgaban de la misma variable
global 'app' con @app.route(...). Todo mezclado: públicas, admin, webhook.

Un Blueprint es un "grupo de rutas portátil" que vive en su propio
archivo. Se define aquí y luego el factory lo "enchufa" a la app con
register_blueprint(). Beneficio de seguridad: las superficies quedan
separadas físicamente. Lo público, lo admin y el webhook en archivos
distintos. Más adelante, al blueprint de admin le aplicamos protección
de login de una sola vez, a todo el grupo.
"""

from flask import Blueprint

# Creamos el blueprint. Primer argumento: nombre interno ("publico").
# Flask lo usa para identificar estas rutas.
publico_bp = Blueprint("publico", __name__)


# @publico_bp.route en vez de @app.route: la ruta se registra en el
# BLUEPRINT, no directo en la app. El factory se encarga de conectarlo.
@publico_bp.route("/inicio")
def inicio():
    return "¡La app vive! Blueprint público funcionando."
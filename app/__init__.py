"""
Application Factory: la "fábrica" que construye la app Flask.

En el app.py viejo, la app se creaba así, suelta y global:

    app = Flask(__name__)
    app.config['DEBUG'] = True
    # ... y todo lo demás colgando de esa variable global

El problema de una app global: solo existe UNA, configurada de UNA forma,
imposible de recrear con otra config (por ejemplo, para tests). Además,
todo termina amontonado en un solo archivo.

La solución profesional es una FUNCIÓN que fabrica la app a pedido:
create_app(). Cada vez que se llama, construye una app fresca y la
configura según el ambiente que le pidas. Eso habilita:
  - elegir configuración (desarrollo/producción/tests) al vuelo
  - registrar blueprints (las superficies separadas: público/admin/webhook)
  - inicializar extensiones de seguridad (rate limiting, etc.)
todo en un lugar ordenado y controlado.
"""

import os
from flask import Flask

from config import config_por_nombre


def create_app(nombre_config=None):
    """
    Construye y devuelve una app Flask configurada.

    nombre_config: "development" o "production". Si no se pasa, se lee
    de la variable FLASK_ENV del .env (y si tampoco está, usa desarrollo).
    """

    # 1. Decidir qué configuración usar.
    # Si nadie especifica, miramos el .env. Por defecto: desarrollo
    # (el ambiente más seguro para equivocarse, porque es tu máquina).
    if nombre_config is None:
        nombre_config = os.environ.get("FLASK_ENV", "development")

    # 2. Crear la instancia de Flask.
    # template_folder le dice a Flask dónde buscar los .html.
    # Como este archivo está dentro de app/, y templates/ también,
    # la ruta es relativa a app/.
    app = Flask(__name__, template_folder="templates")

    # 3. Aplicar la clase de configuración correspondiente.
    # config_por_nombre["production"] -> ProduccionConfig, etc.
    # from_object copia todos los atributos en MAYÚSCULAS de la clase
    # a app.config. Aquí es donde DEBUG, SECRET_KEY y las cookies
    # seguras entran en vigor.
    clase_config = config_por_nombre[nombre_config]
    app.config.from_object(clase_config)

    # 4. Registrar blueprints (las superficies de la app).
    # Todavía no existen; los iremos creando y descomentando uno a uno.
    # Cada blueprint es un grupo de rutas que vive en su propio archivo.
    #
    from app.publico.routes import publico_bp
    app.register_blueprint(publico_bp)

    # 5. Aquí luego inicializaremos extensiones de seguridad
    #    (flask-limiter para rate limiting, logging de auditoría, etc.)

    # 6. Devolver la app ya construida y configurada.
    return app
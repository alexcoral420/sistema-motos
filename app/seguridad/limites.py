"""
Rate limiting: límite de peticiones por tiempo (vulnerabilidad #3).

Sin límites, alguien puede bombardear /login probando miles de
contraseñas por minuto (fuerza bruta), o inundar /webhook con mensajes
falsos y disparar el gasto de la API de Claude.

flask-limiter cuenta las peticiones por IP y, al pasar el límite,
responde con un error 429 ("Too Many Requests") en vez de procesarlas.

Aquí solo CREAMOS el limitador. En el factory lo conectamos a la app,
y en cada ruta decidimos su límite concreto con un decorador.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# get_remote_address identifica al visitante por su dirección IP:
# así el conteo es "por IP", no global. Un atacante en una IP no
# afecta el límite de los demás usuarios.
#
# default_limits: un techo general suave para TODAS las rutas, como
# red de seguridad. Las rutas sensibles (login) tendrán límites más
# estrictos, definidos ruta por ruta.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
)
"""
Punto de entrada de la aplicación.

Su única responsabilidad: llamar a la fábrica create_app() para obtener
una app configurada, y arrancarla en local.

Antes ejecutabas 'python app.py'. Ahora será 'python run.py'.
La diferencia clave: este archivo NO contiene lógica de negocio ni
rutas. Solo enciende el motor. Toda la construcción vive en el factory.
"""

from app import create_app

# Llamamos a la fábrica. Sin argumentos, elige la config según
# FLASK_ENV del .env (development en tu máquina).
app = create_app()


# Este bloque solo se ejecuta cuando corres 'python run.py' directamente.
# En producción NO se usa: allá Railway arranca con gunicorn, que importa
# la variable 'app' de arriba sin ejecutar este bloque.
if __name__ == "__main__":
    # host="127.0.0.1" -> solo accesible desde tu propia máquina (local).
    # NO ponemos debug=True aquí: el debug lo decide la CONFIG según el
    # ambiente. Así respetamos la regla de que producción jamás lo tenga.
    app.run(host="127.0.0.1", port=5000)
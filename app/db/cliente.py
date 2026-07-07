"""
Conexión única a Supabase.

En el database.py viejo, la conexión se creaba suelta al importar:

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

...leyendo las variables con os.getenv directo. Eso significaba que
database.py tenía SU PROPIA copia de la config, separada de config.py.
Dos lugares leyendo credenciales = fácil que se desincronicen.

Aquí centralizamos: una sola función que crea el cliente de Supabase,
usando la config que ya tenemos. El resto del proyecto pide la conexión
llamando a get_supabase(), sin volver a leer variables de entorno.
"""

from supabase import create_client, Client
from config import Config

# Variable a nivel de módulo. Guardará el cliente una vez creado,
# para no reconectar en cada llamada (patrón "singleton" sencillo).
_cliente_supabase = None


def get_supabase() -> Client:
    """
    Devuelve la conexión a Supabase, creándola la primera vez.

    Las llamadas siguientes reutilizan la misma conexión (más eficiente
    que crear una nueva cada vez).
    """
    global _cliente_supabase

    # Si aún no existe, la creamos usando las credenciales de la config.
    if _cliente_supabase is None:
        _cliente_supabase = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_KEY
        )

    return _cliente_supabase
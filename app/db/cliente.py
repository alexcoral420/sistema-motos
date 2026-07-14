"""
Conexión a Supabase con DOS clientes de distinto privilegio.

Principio de mínimo privilegio: cada parte del sistema usa la llave con
el MENOR poder que necesita para su trabajo.

  - Cliente PÚBLICO (llave anon): poco privilegio. Solo puede LEER, y
    solo lo que las políticas RLS permiten. Lo usa el catálogo público,
    que es la superficie más expuesta. Si esta llave se filtrara, el
    daño está acotado: no puede escribir ni borrar nada.

  - Cliente ADMIN (llave service_role): alto privilegio. Salta RLS y
    puede escribir/borrar. Solo lo usan las operaciones de admin, que
    ya están protegidas detrás del login. Su poder queda reservado a
    acciones autenticadas.

Así, la mayoría del tráfico (catálogo) corre con la llave de menor
poder, y el poder alto nunca queda expuesto en superficies públicas.
"""

from supabase import create_client, Client
from config import Config

# Guardamos cada cliente una vez creado (patrón singleton), para no
# reconectar en cada llamada.
_cliente_publico = None
_cliente_admin = None


def get_supabase_publico() -> Client:
    """
    Conexión de BAJO privilegio (llave anon).

    Para operaciones de LECTURA pública (catálogo, detalle de moto).
    Sujeta a las políticas RLS: solo ve lo que las reglas permiten.
    """
    global _cliente_publico
    if _cliente_publico is None:
        _cliente_publico = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_ANON_KEY,
        )
    return _cliente_publico


def get_supabase_admin() -> Client:
    """
    Conexión de ALTO privilegio (llave service_role).

    Para operaciones de ESCRITURA del panel admin (agregar, editar,
    borrar). Salta RLS. Usar SOLO desde código protegido por login.
    """
    global _cliente_admin
    if _cliente_admin is None:
        _cliente_admin = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_KEY,
        )
    return _cliente_admin
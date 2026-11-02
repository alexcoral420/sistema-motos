"""
Consultas del motero. Siempre con el cliente que lleva SU JWT (llave anon):
RLS decide qué filas ve, así que aquí no se filtra por usuario a mano.
Filtrar a mano además de RLS daría una falsa sensación de seguridad: si la
política faltara, el filtro escondería el agujero en vez de mostrarlo.
"""

from app.motero.cliente import cliente_motero


def obtener_perfil(access_token):
    """El perfil del motero (RLS devuelve solo el suyo) o None."""
    resultado = (cliente_motero(access_token).table("perfiles")
                 .select("id, nombre, telefono, version_politica, creado_en")
                 .limit(1)
                 .execute())
    return resultado.data[0] if resultado.data else None


def listar_motos(access_token):
    """Las motos del motero (RLS devuelve solo las suyas), más recientes primero."""
    resultado = (cliente_motero(access_token).table("motos_usuario")
                 .select("id, marca, modelo, placa, anio, creado_en")
                 .order("creado_en", desc=True)
                 .execute())
    return resultado.data or []

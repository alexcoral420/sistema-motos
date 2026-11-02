"""
Consultas del motero. Siempre con el cliente que lleva SU JWT (llave anon):
RLS decide qué filas ve, así que aquí no se filtra por usuario a mano.
Filtrar a mano además de RLS daría una falsa sensación de seguridad: si la
política faltara, el filtro escondería el agujero en vez de mostrarlo.
"""

from app.motero.cliente import cliente_motero

_SELECT_MOTO = "id, marca, modelo, placa, anio, creado_en"


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
                 .select(_SELECT_MOTO)
                 .order("creado_en", desc=True)
                 .execute())
    return resultado.data or []


# Columnas que el motero puede escribir. usuario_id solo en el insert (lo
# pone la ruta desde la sesión; el WITH CHECK de RLS lo valida igual).
_COLUMNAS_MOTO = ("marca", "modelo", "anio", "placa")


def _solo_columnas(datos):
    return {c: datos.get(c) for c in _COLUMNAS_MOTO}


def contar_motos(access_token) -> int:
    resultado = (cliente_motero(access_token).table("motos_usuario")
                 .select("id", count="exact")
                 .limit(1)
                 .execute())
    return resultado.count or 0


def agregar_moto(access_token, usuario_id, datos):
    """Inserta una moto del motero y devuelve la fila creada."""
    fila = {**_solo_columnas(datos), "usuario_id": usuario_id}
    resultado = cliente_motero(access_token).table("motos_usuario").insert(fila).execute()
    return resultado.data[0] if resultado.data else None


def editar_moto(access_token, moto_id, datos):
    """
    Actualiza una moto y devuelve la fila, o None si no afectó ninguna:
    RLS hace invisible una moto ajena, así que editarla toca 0 filas.
    """
    resultado = (cliente_motero(access_token).table("motos_usuario")
                 .update(_solo_columnas(datos))
                 .eq("id", moto_id)
                 .execute())
    return resultado.data[0] if resultado.data else None


def borrar_moto(access_token, moto_id):
    """Borra una moto y devuelve la fila borrada, o None si no era suya o no existía."""
    resultado = (cliente_motero(access_token).table("motos_usuario")
                 .delete()
                 .eq("id", moto_id)
                 .execute())
    return resultado.data[0] if resultado.data else None

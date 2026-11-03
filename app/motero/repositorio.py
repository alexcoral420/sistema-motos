"""
Consultas del motero. Siempre con el cliente que lleva SU JWT (llave anon):
RLS decide qué filas ve, así que aquí no se filtra por usuario a mano.
Filtrar a mano además de RLS daría una falsa sensación de seguridad: si la
política faltara, el filtro escondería el agujero en vez de mostrarlo.
"""

from datetime import datetime, timezone

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


# ---------- dispositivos (suscripciones push) ----------

def guardar_dispositivo(access_token, usuario_id, suscripcion):
    """
    Guarda la suscripción push del motero. Si ese navegador ya estaba
    registrado (mismo endpoint), la actualiza y la reactiva en vez de
    duplicarla: UNIQUE (usuario_id, endpoint) de la migración 023.
    """
    fila = {"usuario_id": usuario_id, "suscripcion": suscripcion, "activo": True}
    resultado = (cliente_motero(access_token).table("dispositivos")
                 .upsert(fila, on_conflict="usuario_id,endpoint")
                 .execute())
    return resultado.data[0] if resultado.data else None


def contar_dispositivos(access_token) -> int:
    """Dispositivos activos del motero (RLS cuenta solo los suyos)."""
    resultado = (cliente_motero(access_token).table("dispositivos")
                 .select("id", count="exact")
                 .eq("activo", True)
                 .limit(1)
                 .execute())
    return resultado.count or 0


# ---------- alertas ----------

_SELECT_ALERTA = ("id, moto_usuario_id, tipo, modo, fecha_objetivo, recurrencia, "
                  "umbrales_dias, activo, creado_en")

# Columnas que el motero puede escribir al crear (usuario_id aparte: lo
# pone la ruta desde la sesión y el WITH CHECK de RLS lo valida igual, como
# que moto_usuario_id, si viene, sea una moto del motero).
_COLUMNAS_ALERTA = ("moto_usuario_id", "tipo", "modo", "recurrencia", "fecha_objetivo", "umbrales_dias")


def listar_alertas(access_token):
    """Las alertas del motero (RLS devuelve solo las suyas), más recientes primero."""
    resultado = (cliente_motero(access_token).table("alertas")
                 .select(_SELECT_ALERTA)
                 .order("creado_en", desc=True)
                 .execute())
    return resultado.data or []


def contar_alertas(access_token, tipo) -> int:
    """Alertas del motero de ese tipo (RLS cuenta solo las suyas)."""
    resultado = (cliente_motero(access_token).table("alertas")
                 .select("id", count="exact")
                 .eq("tipo", tipo)
                 .limit(1)
                 .execute())
    return resultado.count or 0


def crear_alerta(access_token, usuario_id, datos):
    """Inserta una alerta del motero y devuelve la fila creada."""
    fila = {**{c: datos.get(c) for c in _COLUMNAS_ALERTA}, "usuario_id": usuario_id}
    resultado = cliente_motero(access_token).table("alertas").insert(fila).execute()
    return resultado.data[0] if resultado.data else None


def borrar_alerta(access_token, alerta_id):
    """Borra una alerta y devuelve la fila borrada, o None si no era suya o no existía."""
    resultado = (cliente_motero(access_token).table("alertas")
                 .delete()
                 .eq("id", alerta_id)
                 .execute())
    return resultado.data[0] if resultado.data else None


def obtener_alerta_de_moto(access_token, moto_id, tipo):
    """La alerta de ese tipo de la moto, o None (tampoco si la moto es ajena: RLS no la muestra)."""
    resultado = (cliente_motero(access_token).table("alertas")
                 .select(_SELECT_ALERTA)
                 .eq("moto_usuario_id", moto_id)
                 .eq("tipo", tipo)
                 .limit(1)
                 .execute())
    return resultado.data[0] if resultado.data else None


def actualizar_fecha_alerta(access_token, alerta_id, fecha_objetivo):
    """
    Cambia la fecha de una alerta (y la reactiva) y devuelve la fila, o
    None si no afectó ninguna. Solo toca columnas con GRANT de UPDATE.
    """
    cambios = {
        "fecha_objetivo": fecha_objetivo,
        "activo": True,
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    resultado = (cliente_motero(access_token).table("alertas")
                 .update(cambios)
                 .eq("id", alerta_id)
                 .execute())
    return resultado.data[0] if resultado.data else None

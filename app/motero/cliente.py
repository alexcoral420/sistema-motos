"""
Clientes Supabase del motero: llave anon, nunca service_role.

REGLA: el blueprint del motero no importa get_supabase_admin ni
app.db.repositorios. Todo lo que lee o escribe pasa por estos clientes,
así que RLS siempre aplica (lo verifica tests/test_cuentas_motero.py).

Por qué un cliente NUEVO en cada petición y no el singleton público
(get_supabase_publico): supabase-py guarda la sesión dentro del cliente.
Un sign_in o refresh sobre un cliente compartido le cambia el header
Authorization a TODAS las consultas posteriores, de cualquier visitante:
el catálogo público terminaría consultando con el JWT de un motero. Un
cliente por petición, sin persistir sesión ni refrescar en segundo plano,
muere con la petición y no le presta su identidad a nadie.
"""

from flask import g
from supabase import Client, ClientOptions, create_client

from config import Config


def _opciones(headers=None) -> ClientOptions:
    return ClientOptions(
        headers=headers or {},
        persist_session=False,      # la sesión vive en la cookie de Flask, no aquí
        auto_refresh_token=False,   # el refresco lo decide el decorador
    )


def cliente_auth() -> Client:
    """
    Cliente anon para las llamadas a Supabase Auth (sign_up, sign_in,
    refresh, sign_out). Nuevo en cada llamada: es desechable.
    """
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY, _opciones())


def cliente_motero(access_token: str) -> Client:
    """
    Cliente anon con el JWT del motero en el header: PostgREST lo verifica
    y RLS filtra por auth.uid(). Uno por petición (se guarda en flask.g).
    """
    cliente = g.get("_supabase_motero")
    if cliente is None or g.get("_supabase_motero_token") != access_token:
        cliente = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_ANON_KEY,
            _opciones({"Authorization": f"Bearer {access_token}"}),
        )
        g._supabase_motero = cliente
        g._supabase_motero_token = access_token
    return cliente

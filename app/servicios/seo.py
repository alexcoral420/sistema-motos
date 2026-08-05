"""
Servicio de SEO: construye el sitemap del sitio.

El sitemap es la lista de URLs públicas que le entregamos a Google
para que las indexe. NO se escribe a mano: las páginas de detalle de
moto se generan desde el inventario REAL (motos disponibles), igual
que todo lo demás en el sistema. Cuando una moto se vende o entra una
nueva, el sitemap se actualiza solo en la siguiente petición.

Este servicio solo arma la ESTRUCTURA (lista de dicts). Convertirla a
texto XML es responsabilidad de la plantilla, para no mezclar lógica
de negocio con formato de salida.

IMPORTANTE (seguridad y SEO): este sitemap SOLO lista páginas públicas.
Nunca incluye /admin, /login ni /api. Las páginas fijas están escritas
abajo de forma explícita (todas públicas), y las de motos se generan
solo desde motos DISPONIBLES: una moto vendida no tiene página pública
útil, así que no debe indexarse.
"""

from app.servicios import inventario


# Páginas públicas fijas del sitio (no dependen del inventario).
# 'ruta' es relativa; el dominio completo lo antepone la plantilla.
# 'prioridad' (0.0 a 1.0) le sugiere a Google qué tan importante es
# una página frente a otras del MISMO sitio. 'frecuencia' es una pista
# de cada cuánto suele cambiar. Ambas son SUGERENCIAS, no órdenes.
_PAGINAS_FIJAS = [
    {"ruta": "/inicio",     "prioridad": "1.0", "frecuencia": "daily"},
    {"ruta": "/catalogo",   "prioridad": "0.9", "frecuencia": "daily"},
    {"ruta": "/privacidad", "prioridad": "0.3", "frecuencia": "yearly"},
    {"ruta": "/terminos",   "prioridad": "0.3", "frecuencia": "yearly"},
]


def _fecha_moto(moto: dict) -> str | None:
    """
    Saca la fecha para el campo <lastmod> del sitemap desde 'created_at'
    (el campo de fecha que la tabla motos ya tiene). Supabase lo entrega
    en formato ISO ('2026-08-05T14:30:00...'); Google solo necesita la
    parte AAAA-MM-DD, así que cortamos los primeros 10 caracteres.
    Si por alguna razón la moto no trae la fecha, devuelve None y el
    sitemap omite ese dato para esa URL (es opcional).
    """
    fecha = moto.get("created_at")
    return str(fecha)[:10] if fecha else None


def construir_sitemap() -> list[dict]:
    """
    Arma la lista completa de URLs del sitemap.

    Devuelve una lista de dicts con: 'ruta' (relativa), 'prioridad',
    'frecuencia' y opcionalmente 'lastmod'. La plantilla se encarga de
    anteponer el dominio y darle formato XML.

    Solo incluye páginas públicas: las fijas de arriba y una entrada por
    cada moto DISPONIBLE. No incluye páginas privadas (/admin, /login)
    ni rutas puente (/consultar/<id> redirige a WhatsApp: no es
    contenido indexable).
    """
    urls = list(_PAGINAS_FIJAS)

    # Una entrada por cada moto DISPONIBLE. Usamos listar_motos_disponibles
    # (no listar_todas_las_motos): las vendidas no deben indexarse.
    # Estas son las páginas que de verdad posicionan: alguien busca
    # "Yamaha FZ Bogotá" y esta URL individual es la que Google muestra.
    for moto in inventario.listar_motos_disponibles():
        entrada = {
            "ruta": f"/moto/{moto['id']}",
            "prioridad": "0.8",
            "frecuencia": "weekly",
        }
        fecha = _fecha_moto(moto)
        if fecha:
            entrada["lastmod"] = fecha
        urls.append(entrada)

    return urls
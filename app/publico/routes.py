"""
Blueprint público: rutas visibles para cualquiera, sin login.

Rutas: /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.
Cada una llama a la capa de SERVICIOS (inventario), nunca a la base
de datos directo. La ruta solo: recibe la petición, pide datos al
servicio y entrega el HTML. Esa es toda su responsabilidad.
"""

from flask import Blueprint, render_template, request, redirect
from urllib.parse import quote

from app.servicios import catalogo
from app.servicios import inventario
from app.servicios import seo
from app.db import repositorios
publico_bp = Blueprint("publico", __name__)

@publico_bp.route("/")
@publico_bp.route("/inicio")
def inicio():
    """Página de inicio con cifras reales del inventario."""
    motos = inventario.listar_motos_disponibles()
    return render_template(
        "home.html",
        total_motos=len(motos),
        motos_destacadas=repositorios.obtener_motos_mas_consultadas(6),
        marcas=repositorios.obtener_marcas_disponibles(),
    )
    


@publico_bp.route("/catalogo")
def catalogo_publico():
    """
    Catálogo público con filtros.

    Los filtros llegan por la URL (?marca=...&sede=...&q=...).
    El servicio los valida y devuelve todo lo que la página necesita.
    La ruta solo pasa 'request.args' y entrega el HTML: no valida ni
    consulta nada por su cuenta.
    """
    datos = catalogo.buscar_motos(request.args)
    return render_template("catalogo.html", **datos)


@publico_bp.route("/moto/<int:id>")
def detalle_moto(id):
    """Detalle de una moto. es_admin=False -> vista pública."""
    moto = inventario.obtener_moto(id)
    fotos = inventario.obtener_galeria(id)
    return render_template("detalle.html", moto=moto, fotos=fotos, es_admin=False)


@publico_bp.route("/privacidad")
def privacidad():
    """Política de privacidad (contenido estático)."""
    return render_template("privacidad.html")


@publico_bp.route("/terminos")
def terminos():
    """Términos y condiciones (contenido estático)."""
    return render_template("terminos.html")

@publico_bp.route("/consultar/<int:moto_id>")
def consultar_moto(moto_id):
    """
    Registra la intención de compra y redirige a WhatsApp.

    Es una ruta 'puente': el botón del catálogo apunta aquí en vez de
    ir directo a WhatsApp. Registramos el interés (anónimo) y luego
    mandamos a la persona a WhatsApp con el mensaje prellenado.

    Es un GET a propósito: el usuario está 'navegando' hacia WhatsApp.
    No modifica datos del usuario ni requiere protección CSRF; el único
    efecto es incrementar un contador anónimo de interés.
    """
    inventario.registrar_intencion(moto_id)

    # Traemos la moto para armar el mensaje de WhatsApp.
    moto = inventario.obtener_moto(moto_id)
    if not moto:
        # Si no existe, mandamos a WhatsApp sin mensaje específico.
        return redirect("https://wa.me/573204951482")

    mensaje = (f"Hola, He Visto su Catalogo y me interesa la {moto['marca']} {moto['modelo']} "
               f"{moto.get('anio', '')} (Ref: {moto_id})")
    url = f"https://wa.me/573204951482?text={quote(mensaje)}"
    return redirect(url)
    
@publico_bp.route("/sitemap.xml")
def sitemap():
    """
    Sitemap XML para los buscadores.

    Lista las URLs públicas del sitio (home, catálogo, páginas legales
    y cada moto disponible) para que Google las descubra e indexe.

    La ruta solo ORQUESTA, fiel a la arquitectura: pide la lista al
    servicio 'seo', calcula el dominio base y entrega el XML renderizado
    por la plantilla. La lógica de QUÉ URLs entran vive en el servicio;
    el FORMATO XML, en la plantilla. La ruta no decide ni formatea.
    """
    urls = seo.construir_sitemap()

    # request.url_root es la raíz absoluta con la que llegó la petición,
    # p.ej. 'https://universalmotors.online/'. Le quitamos la barra final
    # para que al unir con rutas como '/inicio' no queden dos barras
    # ('...online//inicio').
    dominio = request.url_root.rstrip("/")

    xml = render_template("sitemap.xml", urls=urls, dominio=dominio)

    # Sin este encabezado, el navegador y Google lo interpretarían como
    # HTML. Hay que anunciarlo explícitamente como XML.
    return xml, 200, {"Content-Type": "application/xml"}

@publico_bp.route("/robots.txt")
def robots():
    """
    robots.txt: instrucciones para los buscadores.

    Le dice a Google (y otros buscadores) qué puede rastrear y qué no,
    y dónde está el sitemap. Permite todo lo público y bloquea las
    zonas privadas (panel admin, login, API interna) para que no
    aparezcan en resultados de búsqueda.

    NOTA: esto NO es seguridad — un bot malicioso puede ignorarlo. El
    panel está protegido de verdad por el login. Esto solo evita que
    las rutas privadas se indexen. La seguridad real vive en el login.

    Se sirve desde una ruta (no como archivo estático) para poder
    incluir la URL absoluta del sitemap armada con el dominio real,
    igual que hace la ruta del sitemap.
    """
    dominio = request.url_root.rstrip("/")

    # 'User-agent: *' -> estas reglas aplican a TODOS los buscadores.
    # 'Allow: /'      -> por defecto, pueden rastrear todo el sitio.
    # 'Disallow: ...' -> excepto estas rutas privadas.
    # 'Sitemap: ...'  -> aquí está el mapa del sitio (URL absoluta).
    lineas = [
        "User-agent: *",
        "Allow: /",
        # Acciones privadas del panel (todas cuelgan de la raíz, por eso
        # se listan una a una). NO se incluye '/moto' porque el detalle
        # público '/moto/<id>' SÍ debe indexarse; las acciones de fotos
        # bajo /moto/<id>/... son POST y Google no las rastrea.
        "Disallow: /agregar",
        "Disallow: /comprar",
        "Disallow: /permuta",
        "Disallow: /editar/",
        "Disallow: /vender/",
        "Disallow: /eliminar/",
        "Disallow: /gerencia",
        "Disallow: /usuarios",
        "Disallow: /admin",
        "Disallow: /login",
        "Disallow: /logout",
        "Disallow: /api",
        "Disallow: /consultar",
        "",
        f"Sitemap: {dominio}/sitemap.xml",
    ]
    texto = "\n".join(lineas)

    # Content-Type de texto plano: robots.txt debe servirse como texto,
    # no como HTML.
    return texto, 200, {"Content-Type": "text/plain"}
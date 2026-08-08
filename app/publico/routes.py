"""
Blueprint público: rutas visibles para cualquiera, sin login.

Rutas: /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.
Cada una llama a la capa de SERVICIOS (inventario), nunca a la base
de datos directo. La ruta solo: recibe la petición, pide datos al
servicio y entrega el HTML. Esa es toda su responsabilidad.
"""

from flask import Blueprint, render_template, request, redirect
from urllib.parse import quote
from app.servicios import simulador
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger
from app.servicios.simulador import ErrorSimulador
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
        "Disallow: /admin",     # todo el panel cuelga de aqui
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

@publico_bp.route("/financiacion", methods=["GET", "POST"])
def financiacion():
    """
    Simulador de financiación.

    GET: muestra el simulador. Si viene ?moto_id=N, precarga esa moto.
    POST accion=simular: calcula los 4 planes y los muestra.
    POST accion=registrar: guarda el lead (requiere consentimiento).

    El simulador es orientativo: calcula cuotas estimadas y captura el
    interés del cliente. No decide aprobación de crédito.
    """
    # Datos de la plantilla, se van llenando según la acción.
    contexto = {
        "planes": None,       # resultado de la simulación (los 4 planes)
        "datos": {},          # lo que el usuario ingresó (para recordar)
        "moto": None,         # moto precargada si vino desde el detalle
        "error": None,
        "registrado": False,  # True tras registrar el lead con éxito
    }

    # Moto precargada (desde el botón "Financiar esta moto" del detalle).
    # El moto_id puede venir del query param (enlace del detalle, en GET)
    # o del campo oculto del formulario (en los POST de simular/registrar).
    # Se busca en ambos para que la moto se mantenga en todo el flujo.
    moto_id = request.args.get("moto_id") or request.form.get("moto_id")
    if moto_id and str(moto_id).isdigit():
        moto = inventario.obtener_moto(int(moto_id))
        if moto:
            contexto["moto"] = moto
            contexto["datos"]["valor"] = moto.get("precio")

    if request.method == "POST":
        accion = request.form.get("accion")

        try:
            if accion == "simular":
                valor = validadores.validar_entero(
                    request.form.get("valor"), "valor", minimo=1, maximo=999999999)
                inicial = validadores.validar_entero(
                    request.form.get("cuota_inicial"), "cuota inicial",
                    minimo=0, maximo=999999999, obligatorio=False) or 0

                contexto["planes"] = simulador.simular(valor, inicial)
                contexto["datos"] = {"valor": valor, "cuota_inicial": inicial}

            elif accion == "registrar":
                # Recalcular para tener el monto y volver a mostrar los planes.
                valor = validadores.validar_entero(
                    request.form.get("valor"), "valor", minimo=1, maximo=999999999)
                inicial = validadores.validar_entero(
                    request.form.get("cuota_inicial"), "cuota inicial",
                    minimo=0, maximo=999999999, obligatorio=False) or 0
                mid = request.form.get("moto_id")
                mid = int(mid) if mid and mid.isdigit() else None

                simulador.registrar_lead(
                    nombre=request.form.get("nombre"),
                    telefono=request.form.get("telefono"),
                    correo=request.form.get("correo"),
                    valor_financiar=valor - inicial,
                    cuota_inicial=inicial,
                    moto_id=mid,
                    autorizo=request.form.get("autorizo") == "on",
                )
                obtener_logger().info("Lead de financiación registrado.")
                contexto["registrado"] = True
                contexto["planes"] = simulador.simular(valor, inicial)
                contexto["datos"] = {"valor": valor, "cuota_inicial": inicial}

        except (ErrorSimulador, ErrorValidacion) as e:
            contexto["error"] = e.mensaje

    return render_template("financiacion.html", **contexto)
"""
Blueprint público: rutas visibles para cualquiera, sin login.

Rutas: /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.
Cada una llama a la capa de SERVICIOS (inventario), nunca a la base
de datos directo. La ruta solo: recibe la petición, pide datos al
servicio y entrega el HTML. Esa es toda su responsabilidad.
"""
from app import csrf
from app.seguridad.limites import limiter
from flask import Blueprint, render_template, request, redirect, current_app, session, url_for, jsonify
from urllib.parse import quote
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger
from app.servicios import catalogo
from app.servicios import inventario
from app.servicios import seo
from app.db import repositorios
publico_bp = Blueprint("publico", __name__)



@publico_bp.before_request
def capturar_linea_origen():
    """
    Si el cliente llega por un link con ?linea=X (que un asesor le envió),
    guardamos esa línea en su sesión. Así, cuando el cliente presione
    'Preguntar por esta moto', lo devolvemos al WhatsApp del asesor que
    lo atendió, no al número general.

    La línea persiste en la sesión durante toda la navegación del cliente
    (aunque cambie de filtros o de página), gracias a la cookie de sesión.
    """
    asesor_id = request.args.get("a")
    if asesor_id:
        session["asesor_origen"] = asesor_id
    # Identificador anónimo para agrupar los clics de una misma visita.
    # No dice nada de quién es la persona: es un número al azar.
    if not session.get("visita_id"):
        import uuid
        session["visita_id"] = uuid.uuid4().hex

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
    
@publico_bp.route("/chat", methods=["POST"])
@csrf.exempt
@limiter.limit("15 per minute")
def chat():
    """
    Recibe la conversación del cliente (historial) y devuelve la respuesta
    del asistente. Ruta pública, con rate limiting y validación.
    """
    from flask import jsonify
    datos = request.get_json(silent=True) or {}
    historial = datos.get("historial") or []

    if not isinstance(historial, list) or not historial:
        return jsonify({"error": "Conversación vacía"}), 400
    if len(historial) > 40:
        return jsonify({"error": "Conversación demasiado larga"}), 400
    ultimo = historial[-1].get("texto", "") if historial else ""
    if len(ultimo) > 500:
        return jsonify({"error": "El mensaje es demasiado largo"}), 400

    from app.servicios import asistente
    respuesta = asistente.responder(historial)

    historial_completo = historial + [{"rol": "bot", "texto": respuesta}]
    firmas = session.get("leads_chat_firmas", [])
    diagnostico = asistente.intentar_guardar_lead(historial_completo, firmas)

    if diagnostico["firma"]:
        session["leads_chat_firmas"] = firmas + [diagnostico["firma"]]

    # El servidor verifica que no se prometa lo que no se cumplio.
    respuesta = asistente.corregir_promesa(respuesta, diagnostico, firmas)

    return jsonify({"respuesta": respuesta})

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
@limiter.limit("30 per hour")
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
    inventario.registrar_intencion(moto_id, session.get("visita_id"))
    # El id del asesor de origen (si el cliente vino por un link de asesor).
    asesor_id = session.get("asesor_origen")
    numero = None
    if asesor_id:
        numero = repositorios.obtener_whatsapp_por_id(asesor_id)
    # Si no hay asesor de origen (o no tiene número), usamos el general.
    numero = numero or current_app.config["WHATSAPP_CONTACTO"]
    # Traemos la moto para armar el mensaje de WhatsApp.
    moto = inventario.obtener_moto(moto_id)
    if not moto:
        # Si no existe, mandamos a WhatsApp sin mensaje específico.
        return redirect(f"https://wa.me/{numero}")

        # La URL absoluta permite que el asesor abra la moto directo desde
    # WhatsApp y vea fotos y detalles sin tener que buscarla.
    url_moto = url_for("publico.detalle_moto", id=moto_id, _external=True)

    mensaje = (f"Hola, he visto su catálogo y me interesa comprar la "
               f"{moto['marca']} {moto['modelo']} (Ref #{moto_id})\n\n"
               f"{url_moto}")

    url = f"https://wa.me/{numero}?text={quote(mensaje)}"
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

@publico_bp.route("/financiacion")
def financiacion():
    """
    El simulador con formulario fue reemplazado por el asistente de IA.

    Mantenemos la ruta como redireccion permanente (301) porque la URL
    estuvo publicada: los enlaces viejos siguen funcionando y los
    buscadores transfieren la autoridad de esta pagina a /credito.
    """
    return redirect(url_for("publico.credito"), code=301)

@publico_bp.route("/credito")
def credito():
    """Landing de financiacion: explica el proceso y lleva al asistente."""
    return render_template("credito.html")
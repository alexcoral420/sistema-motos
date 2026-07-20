"""
Blueprint público: rutas visibles para cualquiera, sin login.

Rutas: /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.
Cada una llama a la capa de SERVICIOS (inventario), nunca a la base
de datos directo. La ruta solo: recibe la petición, pide datos al
servicio y entrega el HTML. Esa es toda su responsabilidad.
"""

from flask import Blueprint, render_template, request, redirect
from app.servicios import catalogo
from app.servicios import inventario

publico_bp = Blueprint("publico", __name__)


@publico_bp.route("/inicio")
def inicio():
    """Página principal. Muestra el conteo de motos disponibles."""
    motos = inventario.listar_motos_disponibles()
    return render_template("home.html", total_motos=len(motos))


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

    mensaje = f"Hola, me interesa la {moto['marca']} {moto['modelo']} {moto.get('anio', '')}"
    from urllib.parse import quote
    url = f"https://wa.me/573204951482?text={quote(mensaje)}"
    return redirect(url)
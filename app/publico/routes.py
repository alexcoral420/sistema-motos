"""
Blueprint público: rutas visibles para cualquiera, sin login.

Rutas: /inicio, /catalogo, /moto/<id>, /privacidad, /terminos.
Cada una llama a la capa de SERVICIOS (inventario), nunca a la base
de datos directo. La ruta solo: recibe la petición, pide datos al
servicio y entrega el HTML. Esa es toda su responsabilidad.
"""

from flask import Blueprint, render_template

from app.servicios import inventario

publico_bp = Blueprint("publico", __name__)


@publico_bp.route("/inicio")
def inicio():
    """Página principal. Muestra el conteo de motos disponibles."""
    motos = inventario.listar_motos_disponibles()
    return render_template("home.html", total_motos=len(motos))


@publico_bp.route("/catalogo")
def catalogo():
    """Catálogo público: todas las motos disponibles."""
    motos = inventario.listar_motos_disponibles()
    return render_template("catalogo.html", motos=motos)


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
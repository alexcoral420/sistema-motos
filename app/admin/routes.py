"""
Blueprint de administración: el panel protegido.

TODAS las rutas de aquí llevan @requiere_login. Nadie sin sesión entra.
Esa es la gran ventaja de separar en blueprint: la protección se aplica
ruta por ruta de forma explícita y visible (más adelante veremos cómo
protegerlas en bloque).

Migra las rutas del panel del app.py viejo (/, /agregar, /editar,
/vender, /eliminar, galería admin) a la arquitectura por capas: cada
ruta llama al servicio 'inventario', nunca a la base directo.

Las operaciones de ESCRITURA están en modo prueba (ver inventario.py):
no tocan la base de datos todavía.
"""

from flask import Blueprint, request, render_template, redirect, url_for

from app.servicios import inventario
from app.auth.decorators import requiere_login

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
@requiere_login
def index():
    """Panel principal: lista todas las motos."""
    motos = inventario.listar_todas_las_motos()
    return render_template("index.html", motos=motos)


@admin_bp.route("/agregar", methods=["GET", "POST"])
@requiere_login
def agregar():
    """Formulario para agregar una moto nueva."""
    if request.method == "POST":
        datos = {
            "marca": request.form.get("marca"),
            "modelo": request.form.get("modelo"),
            "anio": int(request.form.get("anio")),
            "color": request.form.get("color"),
            "precio": int(request.form.get("precio")),
            "kilometraje": int(request.form.get("kilometraje")),
            "estado": "disponible",
            "descripcion": request.form.get("descripcion", ""),
            "soat": request.form.get("soat") or None,
            "tecno": request.form.get("tecno") or None,
            "placa": (request.form.get("placa", "") or "").upper() or None,
        }
        inventario.agregar_moto(datos)
        return redirect(url_for("admin.index"))
    return render_template("agregar.html")


@admin_bp.route("/editar/<int:id>", methods=["GET", "POST"])
@requiere_login
def editar(id):
    """Formulario para editar una moto existente."""
    if request.method == "POST":
        datos = {
            "marca": request.form.get("marca"),
            "modelo": request.form.get("modelo"),
            "anio": int(request.form.get("anio")),
            "color": request.form.get("color"),
            "precio": int(request.form.get("precio")),
            "kilometraje": int(request.form.get("kilometraje")),
            "estado": request.form.get("estado"),
            "descripcion": request.form.get("descripcion", ""),
            "soat": request.form.get("soat") or None,
            "tecno": request.form.get("tecno") or None,
            "placa": (request.form.get("placa", "") or "").upper() or None,
        }
        inventario.actualizar_moto(id, datos)
        return redirect(url_for("admin.index"))

    moto = inventario.obtener_moto(id)
    return render_template("editar.html", moto=moto)


@admin_bp.route("/vender/<int:id>")
@requiere_login
def vender(id):
    """Marca una moto como vendida."""
    inventario.marcar_vendida(id)
    return redirect(url_for("admin.index"))


@admin_bp.route("/eliminar/<int:id>")
@requiere_login
def eliminar(id):
    """Elimina una moto."""
    inventario.eliminar_moto(id)
    return redirect(url_for("admin.index"))


@admin_bp.route("/admin/moto/<int:id>")
@requiere_login
def detalle_moto_admin(id):
    """Detalle de una moto en vista admin (es_admin=True)."""
    moto = inventario.obtener_moto(id)
    fotos = inventario.obtener_galeria(id)
    return render_template("detalle.html", moto=moto, fotos=fotos, es_admin=True)
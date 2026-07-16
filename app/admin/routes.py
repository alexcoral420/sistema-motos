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

from flask import Blueprint, request, render_template, redirect, url_for, session

from app.servicios import inventario

from app.servicios import sedes
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger
admin_bp = Blueprint("admin", __name__)

@admin_bp.before_request
def proteger_todo_el_panel():
    """
    Se ejecuta ANTES de cada petición a CUALQUIER ruta de este blueprint.
    Si no hay sesión, registra el intento y redirige al login.
    """
    if "logueado" not in session:
        obtener_logger().warning(
            "Acceso denegado a ruta de admin sin sesión: %s", request.path)
        return redirect(url_for("auth.login"))


@admin_bp.route("/")

def index():
    """Panel principal: lista todas las motos."""
    motos = inventario.listar_todas_las_motos()
    return render_template("index.html", motos=motos)


@admin_bp.route("/agregar", methods=["GET", "POST"])

def agregar():
    """Formulario para agregar una moto nueva, con validación de entrada."""
    if request.method == "POST":
        try:
            # Validamos y limpiamos CADA campo antes de tocar nada.
            # Si cualquiera falla, se lanza ErrorValidacion y saltamos
            # directo al except, sin construir datos a medias.
            datos = {
                "marca": validadores.validar_texto(
                    request.form.get("marca"), "marca", min_len=1, max_len=50),
                "modelo": validadores.validar_texto(
                    request.form.get("modelo"), "modelo", min_len=1, max_len=50),
                "anio": validadores.validar_entero(
                    request.form.get("anio"), "año", minimo=1950, maximo=2100),
                "color": validadores.validar_texto(
                    request.form.get("color"), "color", min_len=1, max_len=30),
                "precio": validadores.validar_entero(
                    request.form.get("precio"), "precio", minimo=0, maximo=999999999),
                "kilometraje": validadores.validar_entero(
                    request.form.get("kilometraje"), "kilometraje", minimo=0, maximo=9999999),
                "estado": "disponible",
                "sede_id": validadores.validar_entero(
                    request.form.get("sede_id"), "sede", minimo=1),
                "descripcion": validadores.validar_texto(
                    request.form.get("descripcion"), "descripción",
                    max_len=1000, obligatorio=False) or "",
                "soat": validadores.validar_texto(
                    request.form.get("soat"), "soat", max_len=20, obligatorio=False),
                "tecno": validadores.validar_texto(
                    request.form.get("tecno"), "tecno", max_len=20, obligatorio=False),
                "placa": validadores.validar_texto(
                    request.form.get("placa"), "placa", max_len=10, obligatorio=False),
            }
            # Lista blanca DINÁMICA: la sede debe existir de verdad en la
            # base. Si mañana agregas una sede, se acepta sola.
            if str(datos["sede_id"]) not in sedes.ids_validos():
                raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
            # La placa, si vino, la normalizamos a mayúsculas.
            if datos["placa"]:
                datos["placa"] = datos["placa"].upper()

            inventario.agregar_moto(datos)
            obtener_logger().info(
                "Admin: moto agregada (%s %s).", datos["marca"], datos["modelo"])
            return redirect(url_for("admin.index"))

        except ErrorValidacion as e:
            return render_template(
                "agregar.html",
                error=e.mensaje,
                datos=request.form,
                sedes=sedes.listar_sedes(),
            )

    return render_template("agregar.html", sedes=sedes.listar_sedes())
@admin_bp.route("/editar/<int:id>", methods=["GET", "POST"])

def editar(id):
    """Formulario para editar una moto existente, con validación de entrada."""
    if request.method == "POST":
        try:
            datos = {
                "marca": validadores.validar_texto(
                    request.form.get("marca"), "marca", min_len=1, max_len=50),
                "modelo": validadores.validar_texto(
                    request.form.get("modelo"), "modelo", min_len=1, max_len=50),
                "anio": validadores.validar_entero(
                    request.form.get("anio"), "año", minimo=1950, maximo=2100),
                "color": validadores.validar_texto(
                    request.form.get("color"), "color", min_len=1, max_len=30),
                "precio": validadores.validar_entero(
                    request.form.get("precio"), "precio", minimo=0, maximo=999999999),
                "kilometraje": validadores.validar_entero(
                    request.form.get("kilometraje"), "kilometraje", minimo=0, maximo=9999999),
                "estado": validadores.validar_opcion(
                    request.form.get("estado"), "estado",
                    opciones_validas=["disponible", "reservado", "vendido"]),
                    "sede_id": validadores.validar_entero(
                    request.form.get("sede_id"), "sede", minimo=1),
                "descripcion": validadores.validar_texto(
                    request.form.get("descripcion"), "descripción",
                    max_len=1000, obligatorio=False) or "",
                "soat": validadores.validar_texto(
                    request.form.get("soat"), "soat", max_len=20, obligatorio=False),
                "tecno": validadores.validar_texto(
                    request.form.get("tecno"), "tecno", max_len=20, obligatorio=False),
                "placa": validadores.validar_texto(
                    request.form.get("placa"), "placa", max_len=10, obligatorio=False),
            }
            if str(datos["sede_id"]) not in sedes.ids_validos():
                raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
            if datos["placa"]:
                datos["placa"] = datos["placa"].upper()

            inventario.actualizar_moto(id, datos)
            obtener_logger().info("Admin: moto id=%s actualizada.", id)
            return redirect(url_for("admin.index"))

        except ErrorValidacion as e:
            return render_template(
                "editar.html",
                error=e.mensaje,
                moto=request.form,
                id=id,
                sedes=sedes.listar_sedes(),
            )

    moto = inventario.obtener_moto(id)
    return render_template("editar.html", moto=moto, id=id, sedes=sedes.listar_sedes())




@admin_bp.route("/vender/<int:id>")

def vender(id):
    """Marca una moto como vendida."""
    inventario.marcar_vendida(id)
    obtener_logger().info("Admin: moto id=%s marcada como vendida.", id)
    return redirect(url_for("admin.index"))


@admin_bp.route("/eliminar/<int:id>")

def eliminar(id):
    """Elimina una moto."""
    inventario.eliminar_moto(id)
    obtener_logger().warning("Admin: moto id=%s eliminada.", id)
    return redirect(url_for("admin.index"))


@admin_bp.route("/admin/moto/<int:id>")
def detalle_moto_admin(id):
    """Detalle de una moto en vista admin (es_admin=True)."""
    moto = inventario.obtener_moto(id)
    fotos = inventario.obtener_galeria(id)
    return render_template("detalle.html", moto=moto, fotos=fotos, es_admin=True)

@admin_bp.route("/moto/<int:id>/subir-fotos", methods=["POST"])
def subir_fotos(id):
    """
    Sube VARIAS fotos de una moto de una sola vez.

    Protegida automáticamente por el before_request del blueprint
    (no necesita decorador: el guardián de la entrada ya la cubre).

    request.files.getlist("fotos") devuelve TODOS los archivos que el
    usuario seleccionó, no solo el primero. Esa es la clave de la
    subida múltiple.
    """
    lista = request.files.getlist("fotos")
    resultado = inventario.subir_fotos_moto(id, lista)

    log = obtener_logger()
    log.info("Admin: %s foto(s) subida(s) a la moto id=%s.",
             resultado["subidas"], id)
    if resultado["rechazadas"]:
        # Registramos los rechazos: útil para auditoría y para detectar
        # si alguien intenta subir archivos que no son imágenes.
        log.warning("Admin: %s archivo(s) rechazado(s) en moto id=%s: %s",
                    len(resultado["rechazadas"]), id, resultado["rechazadas"])

    return redirect(url_for("admin.detalle_moto_admin", id=id))
"""
Blueprint de autenticación: /login y /logout.

El login verifica las credenciales contra la tabla 'usuarios' (no contra
el .env). La sesión guarda la IDENTIDAD del usuario (id, nombre, rol,
sede), lo que habilita la trazabilidad: saber QUIÉN hace cada acción.
"""

from flask import Blueprint, request, render_template, redirect, url_for, session

from app.auth.security import autenticar
from app.seguridad.limites import limiter
from app.seguridad.logging_config import obtener_logger

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    """
    GET  -> muestra el formulario de login.
    POST -> valida usuario + contraseña contra la tabla de usuarios.
    """
    if request.method == "POST":
        usuario_form = request.form.get("usuario", "")
        password = request.form.get("password", "")

        # autenticar() busca al usuario en la tabla, verifica su hash, y
        # devuelve sus datos (rol, sede, nombre) si todo cuadra, o None.
        usuario = autenticar(usuario_form, password)

        log = obtener_logger()
        if usuario:
            # Guardamos la IDENTIDAD, no solo un booleano.
            session["logueado"] = True
            session["usuario_id"] = usuario["id"]
            session["usuario_nombre"] = usuario["nombre_completo"]
            session["rol"] = usuario["rol"]
            session["sede_id"] = usuario["sede_id"]

            log.info("Login exitoso: '%s' (rol: %s).",
                     usuario["usuario"], usuario["rol"])
            return redirect(url_for("admin.index"))
        else:
            # No revelamos si falló el usuario o la contraseña.
            log.warning("Login fallido para el usuario '%s'.", usuario_form)
            return render_template("login.html", error="Usuario o contraseña incorrectos")

    # GET: primera visita al formulario (no es POST).
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Cierra la sesión: limpia toda la identidad guardada."""
    session.clear()
    return redirect(url_for("auth.login"))
"""
Blueprint de autenticación: /login y /logout.

El login verifica las credenciales contra la tabla 'usuarios' (no contra
el .env). La sesión guarda la IDENTIDAD del usuario (id, nombre, rol,
sede), lo que habilita la trazabilidad: saber QUIÉN hace cada acción.
"""

from flask import Blueprint, request, render_template, redirect, url_for, session

from app.auth.security import autenticar
from app.auth.sesion import cerrar_sesion_panel, iniciar_sesion_duradera
from app.auth.destino import CLAVE_DESTINO, destino_tras_login
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
            # Ninguna identidad anterior del panel sobrevive. Solo se borran
            # las claves del panel: la del motero y las del sitio público
            # comparten la cookie y no son de este login.
            pendiente = session.pop(CLAVE_DESTINO, None)
            cerrar_sesion_panel()
            # Guardamos la IDENTIDAD, no solo un booleano.
            session["logueado"] = True
            session["usuario_id"] = usuario["id"]
            session["usuario_nombre"] = usuario["nombre_completo"]
            session["rol"] = usuario["rol"]
            session["sede_id"] = usuario["sede_id"]
            session["whatsapp"] = usuario.get("whatsapp")
            # La sesión dura hasta 10 días (config.DIAS_SESION_PANEL).
            iniciar_sesion_duradera()

            log.info("Login exitoso: '%s' (rol: %s).",
                     usuario["usuario"], usuario["rol"])
            # Cada rol aterriza donde trabaja (gerencia en sus métricas,
            # el asesor en "Mi espacio", los demás en el inventario), salvo
            # que venga de tocar el aviso de un lead: ver destino.py.
            return redirect(destino_tras_login(usuario["rol"], pendiente))
        else:
            # No revelamos si falló el usuario o la contraseña.
            log.warning("Login fallido para el usuario '%s'.", usuario_form)
            return render_template("login.html", error="Usuario o contraseña incorrectos")

    # GET: primera visita al formulario (no es POST).
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Cierra la sesión del panel: limpia su identidad (y solo esa)."""
    cerrar_sesion_panel()
    return redirect(url_for("auth.login"))
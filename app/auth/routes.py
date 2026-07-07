"""
Blueprint de autenticación: /login y /logout.

Diferencia clave con el app.py viejo:
  ANTES:  if usuario == ADMIN_USUARIO and password == ADMIN_PASSWORD
          (comparación en texto plano -> vulnerabilidad #1)
  AHORA:  se compara el usuario, y la contraseña se verifica contra el
          HASH guardado con verificar_password(). La contraseña real
          nunca vive en el servidor.
"""

from flask import Blueprint, request, render_template, redirect, url_for, session

from config import Config
from app.auth.security import verificar_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    GET  -> muestra el formulario de login.
    POST -> valida usuario + contraseña (contra el hash).
    """
    if request.method == "POST":
        usuario = request.form.get("usuario")
        password = request.form.get("password")

        # Dos comprobaciones:
        # 1. El usuario coincide con ADMIN_USUARIO del .env.
        # 2. La contraseña, al hashearse, coincide con ADMIN_PASSWORD_HASH.
        usuario_ok = usuario == Config.ADMIN_USUARIO
        password_ok = verificar_password(Config.ADMIN_PASSWORD_HASH, password)

        if usuario_ok and password_ok:
            # Credenciales correctas: marcamos la sesión como iniciada.
            session["logueado"] = True
            # Al panel admin. Ese blueprint lo crearemos en la fase admin;
            # por ahora apuntamos a su futura ruta de inicio.
            return redirect(url_for("admin.index"))
        else:
            # Credenciales incorrectas: mismo mensaje para usuario o
            # contraseña mal (no revelamos cuál de los dos falló).
            return render_template("login.html", error="Usuario o contraseña incorrectos")

    # GET: primera visita al formulario.
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Cierra la sesión y vuelve al login."""
    session.pop("logueado", None)
    return redirect(url_for("auth.login"))
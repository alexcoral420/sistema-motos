"""
Blueprint del motero: "Mi espacio" (cuentas + motos del cliente final).

Separado del panel a propósito. Las cuentas son de Supabase Auth, no de la
tabla usuarios, y todo lo que este blueprint lee o escribe va con la llave
anon + el JWT del motero, así que RLS aplica siempre.

REGLA: aquí no se importa get_supabase_admin ni app.db.repositorios (ni
nada que los arrastre). Lo verifica tests/test_cuentas_motero.py.

Rutas: /registro, /ingresar, /salir (POST), /mi-espacio, el CRUD de
motos (POST /mi-espacio/motos, /mi-espacio/motos/<id>/editar y /borrar),
las notificaciones (POST /mi-espacio/dispositivos) y las alertas
(POST /mi-espacio/alertas/credito, /mi-espacio/motos/<id>/alertas/<tipo>
para SOAT y tecno, y /mi-espacio/alertas/<id>/borrar).
"""

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, url_for
from supabase import AuthError, PostgrestAPIError

from app.motero import repositorio
from app.motero.cliente import cliente_auth
from app.motero.sesion import (
    cerrar_sesion_motero, guardar_sesion_motero, login_requerido_motero, tokens_motero,
)
from app.seguridad.limites import limiter
from app.seguridad.logging_config import obtener_logger
from app.seguridad.validadores import ErrorValidacion
from app.servicios import alertas_motero, cuentas_motero

motero_bp = Blueprint("motero", __name__)


def _ya_ingresado() -> bool:
    return tokens_motero()[0] is not None


@motero_bp.route("/registro", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def registro():
    if _ya_ingresado():
        return redirect(url_for("motero.mi_espacio"))

    if request.method == "GET":
        return render_template("registro.html", valores={})

    # Para volver a llenar el formulario si algo falla (nunca la contraseña).
    valores = {c: request.form.get(c, "") for c in ("nombre", "email", "telefono")}
    try:
        datos = cuentas_motero.validar_registro(request.form)
    except ErrorValidacion as e:
        return render_template("registro.html", error=e.mensaje, valores=valores), 400

    try:
        respuesta = cliente_auth().auth.sign_up({
            "email": datos["email"],
            "password": datos["password"],
            "options": {
                "data": cuentas_motero.metadata_registro(datos),
                "email_redirect_to": url_for("motero.ingresar", _external=True),
            },
        })
    except AuthError as e:
        obtener_logger().info("Registro de motero rechazado por Supabase: %s", getattr(e, "code", None))
        return render_template(
            "registro.html", valores=valores,
            error=cuentas_motero.mensaje_error_auth(getattr(e, "code", None))), 400

    # Con confirmación de email activa, Supabase no devuelve sesión: el
    # motero entra cuando confirme. Sin confirmación, entra de una vez.
    if respuesta.session:
        guardar_sesion_motero(respuesta.session)
        obtener_logger().info("Motero registrado e ingresado: %s", respuesta.user.id)
        return redirect(url_for("motero.mi_espacio"))

    return render_template("registro.html", pendiente_confirmacion=True,
                           email=datos["email"], valores={})


@motero_bp.route("/ingresar", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def ingresar():
    destino = cuentas_motero.destino_seguro(
        request.values.get("next"), url_for("motero.mi_espacio"))

    if _ya_ingresado():
        return redirect(destino)

    if request.method == "GET":
        return render_template("ingresar.html", siguiente=destino, email="")

    email = request.form.get("email", "")
    try:
        datos = cuentas_motero.validar_ingreso(request.form)
        respuesta = cliente_auth().auth.sign_in_with_password(
            {"email": datos["email"], "password": datos["password"]})
    except ErrorValidacion as e:
        return render_template("ingresar.html", error=e.mensaje,
                               siguiente=destino, email=email), 400
    except AuthError as e:
        obtener_logger().info("Ingreso de motero fallido: %s", getattr(e, "code", None))
        return render_template(
            "ingresar.html", siguiente=destino, email=email,
            error=cuentas_motero.mensaje_error_auth(getattr(e, "code", None))), 400

    guardar_sesion_motero(respuesta.session)
    obtener_logger().info("Ingreso de motero: %s", respuesta.user.id)
    return redirect(destino)


@motero_bp.route("/salir", methods=["POST"])
def salir():
    """
    POST (con CSRF) para que un enlace o <img> de otro sitio no pueda
    cerrarle la sesión a nadie. Revoca la sesión en Supabase y limpia la
    cookie; si Supabase no responde, la cookie se limpia igual.
    """
    access, _ = tokens_motero()
    if access:
        try:
            cliente_auth().auth.admin.sign_out(access, "local")
        except AuthError:
            pass
    cerrar_sesion_motero()
    return redirect(url_for("publico.inicio"))


def _pagina_mi_espacio(estado=200, **extra):
    """Renderiza /mi-espacio; con `extra` se muestra el error de un formulario."""
    token = g.motero["access_token"]
    perfil = repositorio.obtener_perfil(token)
    motos = repositorio.listar_motos(token)
    alertas, alertas_por_moto = alertas_motero.separar_alertas(
        alertas_motero.para_mostrar(repositorio.listar_alertas(token)))
    rangos = {tipo: tuple(f.isoformat() for f in alertas_motero.rango_fecha(tipo))
              for tipo in alertas_motero.TIPOS_ALERTA_FECHA}
    return render_template(
        "mi_espacio.html", motero=g.motero, perfil=perfil, motos=motos,
        max_motos=cuentas_motero.MAX_MOTOS_POR_MOTERO,
        anio_min=cuentas_motero.ANIO_MIN, anio_max=cuentas_motero.anio_maximo(),
        alertas=alertas, alertas_por_moto=alertas_por_moto,
        tipos_por_moto=alertas_motero.TIPOS_POR_MOTO, nombres_tipo=alertas_motero.NOMBRES_TIPO,
        alertas_credito=sum(1 for a in alertas if a.get("tipo") == alertas_motero.TIPO_CREDITO),
        max_alertas_credito=alertas_motero.MAX_ALERTAS_CREDITO,
        fecha_cuota_min=rangos["credito"][0], fecha_cuota_max=rangos["credito"][1],
        rangos_fecha=rangos,
        umbrales_tipo={t: r["umbrales"] for t, r in alertas_motero.TIPOS_ALERTA_FECHA.items()},
        dispositivos_activos=repositorio.contar_dispositivos(token),
        vapid_publica=current_app.config.get("VAPID_PUBLIC_KEY") or "",
        **extra), estado


def _valores_moto():
    return {c: request.form.get(c, "") for c in ("marca", "modelo", "anio", "placa")}


@motero_bp.route("/mi-espacio")
@login_requerido_motero
def mi_espacio():
    return _pagina_mi_espacio()


# ---------- CRUD de motos ----------
# Todo va con el cliente JWT: RLS garantiza que el motero solo toque sus
# filas. Éxito -> redirect (POST-redirect-GET, recargar no repite la
# acción); error -> la misma página con el mensaje sobre el formulario.

LIMITE_MOTOS = "20 per minute"


@motero_bp.route("/mi-espacio/motos", methods=["POST"])
@limiter.limit(LIMITE_MOTOS)
@login_requerido_motero
def agregar_moto():
    token = g.motero["access_token"]
    try:
        datos = cuentas_motero.validar_moto(request.form)
        if repositorio.contar_motos(token) >= cuentas_motero.MAX_MOTOS_POR_MOTERO:
            raise ErrorValidacion(cuentas_motero.MENSAJE_TOPE_MOTOS)
        # usuario_id sale de la sesión, nunca del formulario.
        repositorio.agregar_moto(token, g.motero["id"], datos)
    except ErrorValidacion as e:
        return _pagina_mi_espacio(400, error_agregar=e.mensaje, valores_agregar=_valores_moto())
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: agregar moto rechazado (%s)", g.motero["id"], e.code)
        return _pagina_mi_espacio(400, error_agregar=cuentas_motero.mensaje_error_moto(e.code),
                                  valores_agregar=_valores_moto())
    return redirect(url_for("motero.mi_espacio"))


@motero_bp.route("/mi-espacio/motos/<int:moto_id>/editar", methods=["POST"])
@limiter.limit(LIMITE_MOTOS)
@login_requerido_motero
def editar_moto(moto_id):
    token = g.motero["access_token"]
    error = {"moto_editando": moto_id, "valores_editar": _valores_moto()}
    try:
        datos = cuentas_motero.validar_moto(request.form)
        fila = repositorio.editar_moto(token, moto_id, datos)
    except ErrorValidacion as e:
        return _pagina_mi_espacio(400, error_editar=e.mensaje, **error)
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: editar moto %s rechazado (%s)", g.motero["id"], moto_id, e.code)
        return _pagina_mi_espacio(400, error_editar=cuentas_motero.mensaje_error_moto(e.code), **error)
    if fila is None:
        return _pagina_mi_espacio(404, error_lista=cuentas_motero.MENSAJE_MOTO_NO_ENCONTRADA)
    return redirect(url_for("motero.mi_espacio"))


@motero_bp.route("/mi-espacio/motos/<int:moto_id>/borrar", methods=["POST"])
@limiter.limit(LIMITE_MOTOS)
@login_requerido_motero
def borrar_moto(moto_id):
    try:
        fila = repositorio.borrar_moto(g.motero["access_token"], moto_id)
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: borrar moto %s rechazado (%s)", g.motero["id"], moto_id, e.code)
        return _pagina_mi_espacio(400, error_lista=cuentas_motero.mensaje_error_moto(e.code))
    if fila is None:
        return _pagina_mi_espacio(404, error_lista=cuentas_motero.MENSAJE_MOTO_NO_ENCONTRADA)
    return redirect(url_for("motero.mi_espacio"))


# ---------- notificaciones: dispositivos del motero ----------
# La llama el JS de /mi-espacio con fetch (JSON) después de que el
# navegador dio permiso y creó la suscripción. CSRF va en el header
# X-CSRFToken (CSRFProtect lo acepta igual que el campo del formulario).

@motero_bp.route("/mi-espacio/dispositivos", methods=["POST"])
@limiter.limit("10 per minute")
@login_requerido_motero
def guardar_dispositivo():
    try:
        datos = alertas_motero.validar_dispositivo(request.get_json(silent=True))
        # usuario_id sale de la sesión, nunca del cuerpo de la petición.
        repositorio.guardar_dispositivo(g.motero["access_token"], g.motero["id"], datos["suscripcion"])
    except ErrorValidacion as e:
        return jsonify({"error": e.mensaje}), 400
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: guardar dispositivo rechazado (%s)", g.motero["id"], e.code)
        return jsonify({"error": alertas_motero.mensaje_error_alerta(e.code)}), 400
    return jsonify({"ok": True})


# ---------- alertas ----------
# Igual que las motos: cliente JWT (RLS), POST-redirect-GET al terminar
# bien, la misma página con el mensaje si algo falla.

LIMITE_ALERTAS = "20 per minute"


@motero_bp.route("/mi-espacio/alertas/credito", methods=["POST"])
@limiter.limit(LIMITE_ALERTAS)
@login_requerido_motero
def crear_alerta_credito():
    token = g.motero["access_token"]
    valores = {"fecha_cuota": request.form.get("fecha_cuota", "")}
    try:
        datos = alertas_motero.validar_alerta_credito(request.form)
        if (repositorio.contar_alertas(token, alertas_motero.TIPO_CREDITO)
                >= alertas_motero.MAX_ALERTAS_CREDITO):
            raise ErrorValidacion(alertas_motero.MENSAJE_TOPE_ALERTAS)
        # usuario_id sale de la sesión, nunca del formulario.
        repositorio.crear_alerta(token, g.motero["id"], datos)
    except ErrorValidacion as e:
        return _pagina_mi_espacio(400, error_alerta=e.mensaje, valores_alerta=valores)
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: crear alerta rechazado (%s)", g.motero["id"], e.code)
        return _pagina_mi_espacio(400, error_alerta=alertas_motero.mensaje_error_alerta(e.code),
                                  valores_alerta=valores)
    return redirect(url_for("motero.mi_espacio") + "#alertas")


@motero_bp.route("/mi-espacio/alertas/<int:alerta_id>/borrar", methods=["POST"])
@limiter.limit(LIMITE_ALERTAS)
@login_requerido_motero
def borrar_alerta(alerta_id):
    try:
        fila = repositorio.borrar_alerta(g.motero["access_token"], alerta_id)
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: borrar alerta %s rechazado (%s)", g.motero["id"], alerta_id, e.code)
        return _pagina_mi_espacio(400, error_lista_alertas=alertas_motero.mensaje_error_alerta(e.code))
    if fila is None:
        return _pagina_mi_espacio(404, error_lista_alertas=alertas_motero.MENSAJE_ALERTA_NO_ENCONTRADA)
    # La de una moto vuelve a la tarjeta de esa moto; las demás, a la lista.
    if fila.get("moto_usuario_id"):
        return redirect(url_for("motero.mi_espacio") + f"#moto-{fila['moto_usuario_id']}")
    return redirect(url_for("motero.mi_espacio") + "#alertas")


@motero_bp.route("/mi-espacio/motos/<int:moto_id>/alertas/<tipo>", methods=["POST"])
@limiter.limit(LIMITE_ALERTAS)
@login_requerido_motero
def guardar_alerta_moto(moto_id, tipo):
    """
    Pone o cambia la fecha de vencimiento del SOAT o la tecno de una moto:
    si la moto ya tiene esa alerta se actualiza, si no se crea. Si otra
    petición la creó en el medio, el índice único (migración 024) rechaza
    el insert con 23505 y se actualiza la que quedó.
    """
    if not alertas_motero.es_tipo_por_moto(tipo):
        abort(404)
    token = g.motero["access_token"]
    error = {"alerta_moto_error": (moto_id, tipo),
             "valores_alerta_moto": {"fecha": request.form.get("fecha", "")}}
    try:
        datos = alertas_motero.validar_alerta_moto(tipo, moto_id, request.form)
        fila = _crear_o_actualizar_alerta_moto(token, moto_id, tipo, datos)
    except ErrorValidacion as e:
        return _pagina_mi_espacio(400, error_alerta_moto=e.mensaje, **error)
    except PostgrestAPIError as e:
        obtener_logger().info("Motero %s: alerta %s de moto %s rechazada (%s)",
                              g.motero["id"], tipo, moto_id, e.code)
        if e.code in alertas_motero.CODIGOS_MOTO_AJENA:
            return _pagina_mi_espacio(404, error_lista=cuentas_motero.MENSAJE_MOTO_NO_ENCONTRADA)
        return _pagina_mi_espacio(400, error_alerta_moto=alertas_motero.mensaje_error_alerta(e.code), **error)
    if fila is None:
        return _pagina_mi_espacio(404, error_lista=cuentas_motero.MENSAJE_MOTO_NO_ENCONTRADA)
    return redirect(url_for("motero.mi_espacio") + f"#moto-{moto_id}")


def _crear_o_actualizar_alerta_moto(token, moto_id, tipo, datos):
    existente = repositorio.obtener_alerta_de_moto(token, moto_id, tipo)
    if existente:
        return repositorio.actualizar_fecha_alerta(token, existente["id"], datos["fecha_objetivo"])
    try:
        # usuario_id sale de la sesión; que la moto sea suya lo exige RLS.
        return repositorio.crear_alerta(token, g.motero["id"], datos)
    except PostgrestAPIError as e:
        if e.code != alertas_motero.CODIGO_DUPLICADA:
            raise
        existente = repositorio.obtener_alerta_de_moto(token, moto_id, tipo)
        if existente is None:
            return None
        return repositorio.actualizar_fecha_alerta(token, existente["id"], datos["fecha_objetivo"])

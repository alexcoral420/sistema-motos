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

from flask import Blueprint, request, render_template, redirect, url_for, session, abort
from app.servicios import inventario

from app.servicios import sedes
from app.seguridad import validadores
from app.seguridad.validadores import ErrorValidacion
from app.seguridad.logging_config import obtener_logger
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
from app.auth.decorators import requiere_rol
from app.servicios import busqueda
from app.servicios import reportes
from app.servicios import usuarios

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
@requiere_rol("admin", "asesor", "gerencia", "encargado_sede")
def index():
    """Panel principal: lista las motos, con filtros opcionales."""
    datos = busqueda.buscar(request.args)
    return render_template("index.html", **datos)


@admin_bp.route("/agregar", methods=["GET", "POST"])
@requiere_rol("admin")
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
                "cilindraje": validadores.validar_entero(
                    request.form.get("cilindraje"), "cilindraje", minimo=90, maximo=1200),
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
            # Normalizamos a mayúsculas para consistencia de datos.
            datos["marca"] = datos["marca"].upper()
            datos["modelo"] = datos["modelo"].upper()
            # La placa, si vino, también.
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

@admin_bp.route("/comprar", methods=["GET", "POST"])
@requiere_rol("asesor")   # PROVISIONAL: en el Paso 5 lo dejamos solo "asesor"
def comprar():
    """
    El asesor le compra una moto a un particular.
    Flujo Opción A: agrega la moto al inventario Y registra la compra
    en un solo paso. La identidad del asesor sale de la SESIÓN.
    """
    if request.method == "POST":
        try:
            # Misma validación que 'agregar': cada campo se limpia antes de tocar nada.
            datos = {
                "marca": validadores.validar_texto(
                    request.form.get("marca"), "marca", min_len=1, max_len=50),
                "modelo": validadores.validar_texto(
                    request.form.get("modelo"), "modelo", min_len=1, max_len=50),
                "anio": validadores.validar_entero(
                    request.form.get("anio"), "año", minimo=1950, maximo=2100),
                "cilindraje": validadores.validar_entero(
                    request.form.get("cilindraje"), "cilindraje", minimo=90, maximo=1200),
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
            if str(datos["sede_id"]) not in sedes.ids_validos():
                raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
            datos["marca"] = datos["marca"].upper()
            datos["modelo"] = datos["modelo"].upper()
            if datos["placa"]:
                datos["placa"] = datos["placa"].upper()

            # DIFERENCIA CLAVE vs agregar: un solo paso que agrega la moto
            # Y registra la compra. La identidad sale de la SESIÓN, nunca
            # del formulario: el asesor no puede falsear quién compró.
            inventario.comprar_moto(
                datos,
                session.get("usuario_id"),
                session.get("usuario_nombre"),
            )
            obtener_logger().info(
                "%s compró una moto (%s %s).",
                session.get("usuario_nombre"), datos["marca"], datos["modelo"])
            return redirect(url_for("admin.index"))

        except ErrorValidacion as e:
            return render_template(
                "comprar.html",          # DIFERENCIA: su propio template
                error=e.mensaje,
                datos=request.form,
                sedes=sedes.listar_sedes(),
            )

    # GET: mostrar el formulario vacío.
    # GET: mostrar el formulario vacío.
    return render_template("comprar.html", sedes=sedes.listar_sedes())  

@admin_bp.route("/permuta", methods=["GET", "POST"])
@requiere_rol("asesor")
def permuta():
    """
    El asesor cierra una permuta: el cliente entrega una moto (entrante,
    nueva en el sistema) y se lleva una del inventario (saliente).
    Todo en una sola pantalla. La identidad del asesor sale de la SESIÓN.
    """
    if request.method == "POST":
        try:
            # Datos de la moto ENTRANTE (la del cliente): misma validación
            # que comprar/agregar, cada campo limpio antes de tocar nada.
            datos = {
                "marca": validadores.validar_texto(
                    request.form.get("marca"), "marca", min_len=1, max_len=50),
                "modelo": validadores.validar_texto(
                    request.form.get("modelo"), "modelo", min_len=1, max_len=50),
                "anio": validadores.validar_entero(
                    request.form.get("anio"), "año", minimo=1950, maximo=2100),
                "cilindraje": validadores.validar_entero(
                    request.form.get("cilindraje"), "cilindraje", minimo=90, maximo=1200),
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
            # DIFERENCIA 1: la placa de la moto SALIENTE (la del inventario
            # que se lleva el cliente). Es obligatoria: sin ella no hay permuta.
            placa_saliente = validadores.validar_texto(
                request.form.get("placa_saliente"), "placa de la moto que sale",
                min_len=1, max_len=10)

            if str(datos["sede_id"]) not in sedes.ids_validos():
                raise ErrorValidacion("La sede seleccionada no es válida.", "sede")
            datos["marca"] = datos["marca"].upper()
            datos["modelo"] = datos["modelo"].upper()
            if datos["placa"]:
                datos["placa"] = datos["placa"].upper()

            # DIFERENCIA 2: llamamos a registrar_permuta. Devuelve None si
            # la placa saliente no corresponde a una moto disponible.
            resultado = inventario.registrar_permuta(
                datos,
                placa_saliente,
                session.get("usuario_id"),
                session.get("usuario_nombre"),
            )

            # DIFERENCIA 3: si el servicio devolvió None, la placa saliente
            # no era válida. Avisamos al asesor sin registrar nada.
            if resultado is None:
                raise ErrorValidacion(
                    f"No hay una moto disponible con placa {placa_saliente}.",
                    "placa_saliente")

            obtener_logger().info(
                "%s cerró una permuta (entra %s %s, sale placa %s).",
                session.get("usuario_nombre"),
                datos["marca"], datos["modelo"], placa_saliente)
            return redirect(url_for("admin.index"))

        except ErrorValidacion as e:
            return render_template(
                "permuta.html",
                error=e.mensaje,
                datos=request.form,
                sedes=sedes.listar_sedes(),
            )

    # GET: mostrar el formulario vacío.
    return render_template("permuta.html", sedes=sedes.listar_sedes())

@admin_bp.route("/editar/<int:id>", methods=["GET", "POST"])
@requiere_rol("admin")
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
                    request.form.get("kilometraje"), "kilometraje", minimo=0, maximo=99999),
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

@admin_bp.route("/ventas/cargar-detalle/<int:venta_id>", methods=["GET", "POST"])
@requiere_rol("admin", "gerencia", "encargado_sede")
def cargar_detalle_venta(venta_id):
    """
    Formulario para cargar el detalle de una venta (comprador, pagos, precio).
    GET muestra el formulario; POST lo guarda. Ambos validan que el usuario
    pueda operar esta venta según su sede (muralla de escritura).
    """
    from app.servicios import detalle_ventas

    # Aislamiento de ESCRITURA: ¿esta venta está en el alcance del usuario?
    venta = detalle_ventas.venta_en_alcance(venta_id)
    if not venta:
        abort(403)

    if request.method == "POST":
        try:
            datos_comprador = {
                "nombre": request.form.get("comprador_nombre"),
                "cedula": request.form.get("comprador_cedula"),
                "telefono": request.form.get("comprador_telefono"),
                "correo": request.form.get("comprador_correo"),
            }
            metodos = request.form.getlist("pago_metodo")
            entidades = request.form.getlist("pago_entidad")
            montos = request.form.getlist("pago_monto")
            lista_pagos = [
                {"metodo": m, "entidad": e, "monto": mo}
                for m, e, mo in zip(metodos, entidades, montos)
            ]
            precio = request.form.get("precio_venta")

            aviso = detalle_ventas.guardar_detalle(
                venta_id, datos_comprador, lista_pagos, precio
            )
            obtener_logger().info("Detalle cargado para venta id=%s por %s.",
                                  venta_id, session.get("usuario_nombre"))
            return render_template("detalle_guardado.html", aviso=aviso)

        except ErrorValidacion as e:
            return render_template(
                "cargar_detalle_venta.html",
                venta=venta,
                error=e.mensaje,
                datos=request.form,
            )

    # GET: mostrar el formulario vacío.
    return render_template("cargar_detalle_venta.html", venta=venta)


@admin_bp.route("/vender/<int:id>", methods=["POST"])
@requiere_rol("admin", "asesor", "gerencia", "encargado_sede")
def vender(id):
    """Marca una moto como vendida y registra quién la vendió."""
    inventario.marcar_vendida(id)

    # Registro histórico: quién vendió qué. La identidad sale de la
    # SESIÓN, no del formulario: el usuario no puede falsear quién es.
    inventario.registrar_venta(
        id,
        session.get("usuario_id"),
        session.get("usuario_nombre"),
    )

    obtener_logger().info("%s marcó como vendida la moto id=%s.",
                          session.get("usuario_nombre"), id)
    return redirect(url_for("admin.index"))


@admin_bp.route("/eliminar/<int:id>", methods=["POST"])
@requiere_rol("admin")
def eliminar(id):
    """Elimina una moto."""
    inventario.eliminar_moto(id)
    obtener_logger().warning("Admin: moto id=%s eliminada.", id)
    return redirect(url_for("admin.index"))




ROLES_DATOS_CONTRATO = ("admin", "gerencia", "encargado_sede")


@admin_bp.route("/moto/<int:id>")
@requiere_rol("admin", "asesor", "gerencia", "encargado_sede")
def detalle_moto_admin(id):
    """
    Detalle de una moto en vista admin (es_admin=True). Para los roles
    que cargan datos de contrato, y solo si la moto es de su alcance
    de sede, incluye la sección del RUNT.
    """
    from app.servicios import contratos

    moto = inventario.obtener_moto(id)
    fotos = inventario.obtener_galeria(id)

    puede_cargar_contrato = False
    datos_contrato = None
    if session.get("rol") in ROLES_DATOS_CONTRATO and contratos.moto_en_alcance(id):
        puede_cargar_contrato = True
        datos_contrato = contratos.obtener_datos(id)

    return render_template(
        "detalle.html", moto=moto, fotos=fotos, es_admin=True,
        puede_cargar_contrato=puede_cargar_contrato,
        datos_contrato=datos_contrato,
        etiquetas_contrato=contratos.ETIQUETAS_VISIBLES,
        contrato_guardado=request.args.get("contrato_guardado"),
        contrato_error=request.args.get("contrato_error"),
    )


@admin_bp.route("/moto/<int:id>/datos-contrato", methods=["POST"])
@requiere_rol(*ROLES_DATOS_CONTRATO)
def guardar_datos_contrato(id):
    """
    Recibe el texto pegado del RUNT, lo parsea y guarda los datos de
    contrato de la moto. El servicio valida el alcance de sede: un
    encargado no puede cargar datos a una moto de otra sede cambiando
    el id de la URL.
    """
    from app.servicios import contratos

    try:
        contratos.procesar_y_guardar(id, request.form.get("texto_runt"))
        obtener_logger().info("Datos de contrato (RUNT) cargados para moto id=%s por %s.",
                              id, session.get("usuario_nombre"))
        return redirect(url_for("admin.detalle_moto_admin", id=id, contrato_guardado=1,
                                _anchor="datos-contrato"))
    except ErrorValidacion as e:
        return redirect(url_for("admin.detalle_moto_admin", id=id, contrato_error=e.mensaje,
                                _anchor="datos-contrato"))

@admin_bp.route("/moto/<int:id>/subir-fotos", methods=["POST"])
@requiere_rol("admin")
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

@admin_bp.route("/moto/<int:id>/foto/<int:foto_id>/eliminar", methods=["POST"])
@requiere_rol("admin")
def eliminar_foto_moto(id, foto_id):
    """Elimina una foto de la galería de una moto."""
    ok = inventario.eliminar_foto(id, foto_id)
    log = obtener_logger()
    if ok:
        log.warning("Admin: foto id=%s eliminada de la moto id=%s.", foto_id, id)
    else:
        # Un intento fallido puede significar que alguien pasó ids que no
        # corresponden: vale la pena dejarlo registrado.
        log.warning("Admin: intento fallido de borrar foto id=%s en moto id=%s.",
                    foto_id, id)
    return redirect(url_for("admin.detalle_moto_admin", id=id))


@admin_bp.route("/moto/<int:id>/portada/eliminar", methods=["POST"])
@requiere_rol("admin")
def eliminar_portada_moto(id):
    """Elimina la portada. La primera de galería la reemplaza (si hay)."""
    inventario.eliminar_portada(id)
    obtener_logger().warning("Admin: portada eliminada de la moto id=%s.", id)
    return redirect(url_for("admin.detalle_moto_admin", id=id))


@admin_bp.route("/moto/<int:id>/foto/<int:foto_id>/portada", methods=["POST"])
@requiere_rol("admin")
def hacer_portada_moto(id, foto_id):
    """Convierte una foto de galería en portada (la anterior baja a galería)."""
    inventario.hacer_portada(id, foto_id)
    obtener_logger().info("Admin: foto id=%s puesta como portada de la moto id=%s.",
                          foto_id, id)
    return redirect(url_for("admin.detalle_moto_admin", id=id))
@admin_bp.route("/gerencia")
@requiere_rol("admin", "gerencia")
def panel_gerencia():
    """Panel de métricas del negocio. Solo admin y gerencia."""
    return render_template(
        "gerencia.html",
        ventas_usuario=reportes.ventas_por_usuario(
            desde=request.args.get("desde"),
            hasta=request.args.get("hasta"),
        ),
        ventas_semana=reportes.ventas_por_semana(),
        ventas_detalle=reportes.ventas_detalle(
            desde=request.args.get("desde"),
            hasta=request.args.get("hasta"),
            orden=request.args.get("orden"),
        ),
        compras_usuario=reportes.compras_por_usuario(
            desde=request.args.get("desde"),
            hasta=request.args.get("hasta"),
        ),
        compras_detalle=reportes.compras_detalle(
            desde=request.args.get("desde"),
            hasta=request.args.get("hasta"),
            orden=request.args.get("orden"),
        ),
        documentos_vencer=reportes.documentos_por_vencer(),
        motos_consultadas=reportes.motos_mas_consultadas(),
        consultas_marca=reportes.consultas_por_marca(),
        permutas_usuario=reportes.permutas_por_usuario(),
        modelos_permutados=reportes.modelos_permutados(),
    )

@admin_bp.route("/ventas/pendientes-detalle")
@requiere_rol("admin", "gerencia", "encargado_sede")
def vista_ventas_pendientes():
    """
    Lista las ventas verificadas que aún no tienen el detalle cargado.
    El aislamiento por sede lo aplica el servicio: gerencia/admin ven
    todas, el encargado solo las de su sede.
    """
    from app.servicios import detalle_ventas
    pendientes = detalle_ventas.listar_pendientes()
    return render_template("ventas_detalle_pendientes.html", pendientes=pendientes)


@admin_bp.route("/ventas")
@requiere_rol("admin", "gerencia", "encargado_sede")
def ventas_mi_sede():
    """
    Vista unificada de ventas: verificar, cargar detalle o ver completas.
    El aislamiento por sede lo aplica el servicio: gerencia/admin ven
    todas, el encargado solo las de su sede.
    """
    from app.servicios import detalle_ventas
    ventas = detalle_ventas.listar_ventas_de_mi_sede()
    return render_template("ventas_mi_sede.html", ventas=ventas)


# ============================================================
#  GASTOS (taller, repuestos, lavadero — por moto)
# ============================================================

@admin_bp.route("/gastos")
@requiere_rol("admin", "gerencia", "encargado_sede")
def ver_gastos():
    """
    Panel de gastos de una moto: buscar por placa, ver el historial
    (taller + manuales) y su total. Sin placa en la URL, solo muestra
    el buscador.
    """
    from app.servicios import gastos

    placa = (request.args.get("placa") or "").strip().upper()
    moto = None
    lista_gastos = []
    total = 0
    error = request.args.get("error")

    if placa:
        moto = gastos.moto_por_placa_en_alcance(placa)
        if not moto:
            error = error or "La moto no existe o no pertenece a su sede."
        else:
            lista_gastos, total = gastos.listar_gastos(moto["id"])

    aviso = None
    if request.args.get("guardado"):
        aviso = "Gasto guardado correctamente."
    elif request.args.get("sincronizado") is not None:
        aviso = f"Sincronización completa: {request.args.get('sincronizado')} gasto(s) nuevo(s) del taller."
    elif request.args.get("taller_off"):
        aviso = "El taller no respondió. Intente sincronizar de nuevo más tarde."

    return render_template(
        "gastos_moto.html",
        placa=placa, moto=moto, gastos=lista_gastos, total=total,
        error=error, aviso=aviso,
    )


@admin_bp.route("/gastos/manual", methods=["POST"])
@requiere_rol("admin", "gerencia", "encargado_sede")
def guardar_gasto_manual():
    """Carga un gasto manual (repuesto o lavadero) para una moto."""
    from app.servicios import gastos

    placa = (request.form.get("placa") or "").strip().upper()
    try:
        gastos.crear_gasto_manual(
            placa=placa,
            tipo=request.form.get("tipo"),
            concepto=request.form.get("concepto"),
            monto=request.form.get("monto"),
            fecha_gasto=request.form.get("fecha_gasto"),
            usuario_id=session.get("usuario_id"),
        )
        obtener_logger().info("%s cargó un gasto manual para placa=%s.",
                              session.get("usuario_nombre"), placa)
        return redirect(url_for("admin.ver_gastos", placa=placa, guardado=1))
    except ErrorValidacion as e:
        return redirect(url_for("admin.ver_gastos", placa=placa, error=e.mensaje))


@admin_bp.route("/gastos/sincronizar", methods=["POST"])
@requiere_rol("admin", "gerencia", "encargado_sede")
def sincronizar_gastos_taller():
    """Trae del taller las órdenes nuevas de una moto y las guarda como gasto."""
    from app.servicios import gastos

    placa = (request.form.get("placa") or "").strip().upper()
    try:
        cantidad, aviso_taller = gastos.sincronizar_taller(placa)
        obtener_logger().info("%s sincronizó taller para placa=%s (%s gasto(s) nuevos).",
                              session.get("usuario_nombre"), placa, cantidad)
        if aviso_taller:
            return redirect(url_for("admin.ver_gastos", placa=placa, taller_off=1))
        return redirect(url_for("admin.ver_gastos", placa=placa, sincronizado=cantidad))
    except ErrorValidacion as e:
        return redirect(url_for("admin.ver_gastos", placa=placa, error=e.mensaje))


@admin_bp.route("/gerencia/verificar-venta/<int:venta_id>", methods=["POST"])
@requiere_rol("admin", "gerencia", "encargado_sede")
def verificar_venta(venta_id):
    """
    Marca una venta como verificada. Gerencia/admin cualquiera; el
    encargado solo las de su sede (lo valida el servicio).

    Quien verifica sale de la SESION, no del formulario: nadie puede
    firmar la verificacion a nombre de otro.
    """
    try:
        reportes.verificar_venta(venta_id, session.get("usuario_nombre"))
    except ErrorValidacion:
        obtener_logger().warning("%s intento verificar la venta id=%s fuera de su alcance.",
                                 session.get("usuario_nombre"), venta_id)
        abort(403)

    obtener_logger().info("%s verifico la venta id=%s.",
                          session.get("usuario_nombre"), venta_id)

    # El encargado no tiene acceso al panel de gerencia: vuelve a su vista.
    # "origen" solo elige entre dos destinos fijos, nunca una URL libre.
    if session.get("rol") == "encargado_sede" or request.form.get("origen") == "ventas":
        return redirect(url_for("admin.ventas_mi_sede"))
    return redirect(url_for("admin.panel_gerencia"))

@admin_bp.route("/gerencia/verificar-compra/<int:compra_id>", methods=["POST"])
@requiere_rol("admin", "gerencia")
def verificar_compra(compra_id):
    """
    Marca una compra como verificada. Solo gerencia y admin.
    Quien verifica sale de la SESION, no del formulario.
    """
    reportes.verificar_compra(compra_id, session.get("usuario_nombre"))

    obtener_logger().info("%s verifico la compra id=%s.",
                          session.get("usuario_nombre"), compra_id)
    return redirect(url_for("admin.panel_gerencia"))


@admin_bp.route("/usuarios", methods=["GET", "POST"])
@requiere_rol("admin", "gerencia")
def gestion_usuarios():
    """Panel de gestión de usuarios: listar y crear."""
    error = None
    exito = None

    if request.method == "POST":
        try:
            # La identidad de QUIEN crea viene de la SESIÓN, nunca del form.
            usuarios.crear(
                actor_rol=session.get("rol"),
                usuario=request.form.get("usuario"),
                nombre=request.form.get("nombre_completo"),
                password=request.form.get("password"),
                rol=request.form.get("rol"),
                sede_id=request.form.get("sede_id") or None,
            )
            exito = "Usuario creado correctamente."
        except usuarios.ErrorGestionUsuario as e:
            error = str(e)

    return render_template(
        "usuarios.html",
        lista_usuarios=usuarios.listar(),
        sedes=sedes.listar_sedes(),
        error=error,
        exito=exito,
    )




@admin_bp.route("/usuarios/<int:usuario_id>/desactivar", methods=["POST"])
@requiere_rol("admin", "gerencia")
def desactivar_usuario(usuario_id):
    """Desactiva un usuario (borrado lógico) con salvaguardas."""
    try:
        # Actor id y rol: de la SESIÓN. objetivo: de la URL.
        usuarios.desactivar(
            actor_id=session.get("usuario_id"),
            actor_rol=session.get("rol"),
            objetivo_id=usuario_id,
        )
    except usuarios.ErrorGestionUsuario as e:
        # Guardamos el mensaje para mostrarlo al volver.
        obtener_logger().info("Desactivación rechazada: %s", str(e))

    return redirect(url_for("admin.gestion_usuarios"))
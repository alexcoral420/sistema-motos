"""
Pruebas de la bandeja de leads del chat (/admin/leads, migración 029), del
seguimiento que hace el asesor (migración 030) y del aviso push.

No tocan la base ni los servicios de push: el repositorio y el envío se
reemplazan con monkeypatch. Correr desde la raíz:  python -m pytest tests/
"""

from datetime import date
from pathlib import Path

import pytest
from flask import Flask

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import leads_chat, notificaciones_staff, push

RAIZ = Path(__file__).resolve().parent.parent
ASESOR, OTRO_ASESOR = 10, 11
HOY = date(2026, 11, 11)


def lead(**cambios):
    base = {
        "id": 1, "created_at": "2026-11-10T20:45:00+00:00",
        "nombre": "Ana Perez", "telefono": "3001234567", "correo": "ana@correo.com",
        "moto_id": None, "moto_interes": "Yamaha FZ 2019", "forma_pago": "financiado",
        "estado": "nuevo", "asesor_id": None, "asesor_nombre": None,
        "tomado_en": None, "gestionado_en": None, "proximo_contacto": None, "motos": None,
    }
    base.update(cambios)
    return base


# ------------------------------------------------------------
# Qué ve cada quién
# ------------------------------------------------------------

def test_asesor_no_ve_el_contacto_de_un_lead_sin_tomar():
    visto = leads_chat._presentar(lead(), ASESOR, "asesor")
    assert visto["nombre"] == "Ana"
    assert visto["telefono"] is None and visto["correo"] is None
    assert visto["whatsapp_url"] is None
    assert visto["puede_tomar"] and not visto["puede_gestionar"]


def test_asesor_ve_el_contacto_de_su_lead():
    suyo = lead(estado="tomado", asesor_id=ASESOR, asesor_nombre="Luis")
    visto = leads_chat._presentar(suyo, ASESOR, "asesor")
    assert visto["nombre"] == "Ana Perez" and visto["telefono"] == "3001234567"
    assert visto["whatsapp_url"].startswith("https://wa.me/573001234567?text=")
    assert visto["propio"] and visto["puede_gestionar"] and not visto["puede_tomar"]


@pytest.mark.parametrize("rol", ["admin", "gerencia"])
def test_admin_y_gerencia_ven_el_contacto_pero_no_toman(rol):
    visto = leads_chat._presentar(lead(), 99, rol)
    assert visto["telefono"] == "3001234567"
    assert not visto["puede_tomar"]


def test_solo_admin_gestiona_un_lead_ajeno():
    ajeno = lead(estado="tomado", asesor_id=OTRO_ASESOR)
    assert leads_chat._presentar(ajeno, 99, "admin")["puede_gestionar"]
    assert not leads_chat._presentar(ajeno, 99, "gerencia")["puede_gestionar"]


def test_compra_de_contado_es_prioridad():
    visto = leads_chat._presentar(lead(forma_pago="contado"), ASESOR, "asesor")
    assert visto["prioridad"] and visto["forma_pago_texto"] == "Compra de contado"
    assert not leads_chat._presentar(lead(), ASESOR, "asesor")["prioridad"]


def test_la_moto_de_la_ficha_gana_sobre_la_nombrada_y_la_hora_es_de_colombia():
    con_ficha = lead(moto_id=7, motos={"marca": "Honda", "modelo": "CB125F", "anio": 2023, "precio": 5500000})
    visto = leads_chat._presentar(con_ficha, ASESOR, "asesor")
    assert visto["moto_texto"] == "Honda CB125F 2023" and visto["moto_precio"] == 5500000
    assert visto["recibido"] == "10 de noviembre, 3:45 p. m."   # 20:45 UTC


def test_listar_pone_primero_los_de_contado_y_agrupa(monkeypatch):
    filas = [
        lead(id=1), lead(id=2, forma_pago="contado"), lead(id=3),
        lead(id=4, estado="tomado", asesor_id=ASESOR),
        lead(id=5, estado="vendido", asesor_id=ASESOR),
    ]
    pedido = []
    monkeypatch.setattr(repositorios, "listar_leads_bandeja",
                        lambda asesor_id=None: pedido.append(asesor_id) or filas)

    grupos = leads_chat.listar(ASESOR, "asesor")
    assert [l["id"] for l in grupos["nuevos"]] == [2, 1, 3]
    assert [l["id"] for l in grupos["en_gestion"]] == [4]
    assert [l["id"] for l in grupos["cerrados"]] == [5]

    leads_chat.listar(99, "gerencia")
    assert pedido == [ASESOR, None]     # el asesor filtra por él; gerencia ve todo


def test_asesor_no_abre_el_lead_que_tomo_otro(monkeypatch):
    monkeypatch.setattr(repositorios, "listar_notas_lead", lambda _id: [])
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja",
                        lambda _id: lead(estado="tomado", asesor_id=OTRO_ASESOR))
    assert leads_chat.obtener(1, ASESOR, "asesor") is None
    assert leads_chat.obtener(1, 99, "admin") is not None
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja", lambda _id: None)
    assert leads_chat.obtener(1, 99, "admin") is None


# ------------------------------------------------------------
# Tomar y cerrar
# ------------------------------------------------------------

def test_tomar_asigna_al_asesor_de_la_sesion(monkeypatch):
    llamadas = []

    def tomar(lead_id, estado_requerido, cambios):
        llamadas.append((lead_id, estado_requerido, cambios))
        return {"id": lead_id}

    monkeypatch.setattr(repositorios, "tomar_lead_chat", tomar)
    leads_chat.tomar(1, ASESOR, "Luis Gomez", "asesor")
    lead_id, requerido, cambios = llamadas[0]
    assert (lead_id, requerido) == (1, "nuevo")
    assert cambios["estado"] == "tomado"
    assert cambios["asesor_id"] == ASESOR and cambios["asesor_nombre"] == "Luis Gomez"
    assert cambios["tomado_en"]


def test_si_otro_lo_tomo_primero_se_informa(monkeypatch):
    monkeypatch.setattr(repositorios, "tomar_lead_chat", lambda *a, **k: None)
    with pytest.raises(ErrorValidacion, match="Otro asesor"):
        leads_chat.tomar(1, ASESOR, "Luis", "asesor")


@pytest.mark.parametrize("rol", ["admin", "gerencia", "encargado_sede"])
def test_solo_el_asesor_toma(monkeypatch, rol):
    monkeypatch.setattr(repositorios, "tomar_lead_chat",
                        lambda *a, **k: pytest.fail("no debe llegar a la base"))
    with pytest.raises(ErrorValidacion):
        leads_chat.tomar(1, 99, "X", rol)


# ------------------------------------------------------------
# Seguimiento: etapas, próximo contacto y notas
# ------------------------------------------------------------

@pytest.fixture
def base(monkeypatch):
    """
    Un lead en memoria con su línea de tiempo. Devuelve un dict con
    'lead' (la fila), 'cambios' (cada UPDATE pedido) y 'notas' (lo insertado).
    """
    estado = {"lead": lead(estado="tomado", asesor_id=ASESOR, asesor_nombre="Luis"),
              "cambios": [], "notas": []}

    def cambiar(lead_id, estados_permitidos, cambios, asesor_id=None):
        estado["cambios"].append((estados_permitidos, cambios, asesor_id))
        fila = estado["lead"]
        if fila["estado"] not in estados_permitidos:
            return None
        if asesor_id is not None and fila["asesor_id"] != asesor_id:
            return None
        fila.update(cambios)
        return fila

    monkeypatch.setattr(repositorios, "obtener_lead_bandeja", lambda _id: estado["lead"])
    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat", cambiar)
    monkeypatch.setattr(repositorios, "agregar_notas_lead",
                        lambda filas: estado["notas"].extend(filas) or filas)
    monkeypatch.setattr(repositorios, "listar_notas_lead", lambda _id: [])
    return estado


def seguir(datos, usuario_id=ASESOR, rol="asesor"):
    leads_chat.registrar_seguimiento(1, datos, usuario_id, "Luis Gomez", rol, hoy=HOY)


def test_tomado_se_muestra_como_por_contactar_y_contactado_como_primer_contacto():
    tomado = leads_chat._presentar(lead(estado="tomado", asesor_id=ASESOR), ASESOR, "asesor")
    assert tomado["estado_texto"] == "Por contactar"
    viejo = leads_chat._presentar(lead(estado="contactado", asesor_id=ASESOR), ASESOR, "asesor")
    assert viejo["estado"] == "primer_contacto" and viejo["abierto"]


def test_cambiar_de_etapa_deja_un_renglon_en_el_historial(base):
    seguir({"estado": "primer_contacto"})
    permitidos, cambios, asesor_id = base["cambios"][0]
    # Condicionado al estado que se leyó y al asesor de la sesión.
    assert permitidos == ["tomado"] and asesor_id == ASESOR
    assert cambios["estado"] == "primer_contacto" and cambios["gestionado_en"]
    assert base["notas"] == [{"lead_id": 1, "usuario_id": ASESOR, "usuario_nombre": "Luis Gomez",
                              "tipo": "evento", "texto": "Estado: Primer contacto"}]


def test_se_puede_saltar_etapas_y_volver_atras(base):
    seguir({"estado": "cita_pendiente"})
    seguir({"estado": "primer_contacto"})
    assert base["lead"]["estado"] == "primer_contacto"


def test_nota_sola_no_toca_el_lead(base):
    seguir({"estado": "tomado", "proximo_contacto": "",
            "nota": "  Llamar despues de las 5\r\nPrefiere WhatsApp  "})
    assert base["cambios"] == []
    assert base["notas"] == [{"lead_id": 1, "usuario_id": ASESOR, "usuario_nombre": "Luis Gomez",
                              "tipo": "nota", "texto": "Llamar despues de las 5\nPrefiere WhatsApp"}]


def test_programar_el_proximo_contacto_con_nota(base):
    seguir({"estado": "primer_contacto", "proximo_contacto": "2026-12-11",
            "nota": "Contactar dentro de un mes"})
    assert base["lead"]["proximo_contacto"] == "2026-12-11"
    assert [n["tipo"] for n in base["notas"]] == ["evento", "nota"]
    assert base["notas"][0]["texto"] == ("Estado: Primer contacto · "
                                         "Próximo contacto: 11 de diciembre de 2026")


def test_quitar_la_fecha_y_no_tocarla_si_el_campo_no_llega(base):
    base["lead"]["proximo_contacto"] = "2026-11-20"
    seguir({"nota": "sigue interesado"})                 # sin el campo: la fecha se queda
    assert base["cambios"] == [] and base["lead"]["proximo_contacto"] == "2026-11-20"
    seguir({"proximo_contacto": ""})                     # vacío: se quita
    assert base["lead"]["proximo_contacto"] is None
    assert base["notas"][-1]["texto"] == "Sin próximo contacto programado"


@pytest.mark.parametrize("fecha", ["2026-11-10", "2027-11-12", "manana", "2026-13-40"])
def test_fecha_pasada_lejana_o_invalida_se_rechaza(base, fecha):
    with pytest.raises(ErrorValidacion):
        seguir({"proximo_contacto": fecha})
    assert base["cambios"] == [] and base["notas"] == []


def test_una_fecha_ya_atrasada_no_impide_agregar_una_nota(base):
    base["lead"]["proximo_contacto"] = "2026-11-01"
    seguir({"proximo_contacto": "2026-11-01", "nota": "no contesto"})
    assert base["cambios"] == [] and base["notas"][0]["texto"] == "no contesto"


@pytest.mark.parametrize("cierre", ["vendido", "descartado"])
def test_cerrar_quita_el_proximo_contacto(base, cierre):
    base["lead"]["proximo_contacto"] = "2026-11-20"
    seguir({"estado": cierre, "proximo_contacto": "2026-12-01"})
    assert base["lead"]["estado"] == cierre and base["lead"]["proximo_contacto"] is None
    assert base["notas"][0]["texto"] == f"Estado: {leads_chat.ETIQUETAS_ESTADO[cierre]}"


def test_un_lead_cerrado_se_puede_reabrir(base):
    base["lead"]["estado"] = "descartado"
    seguir({"estado": "segundo_contacto", "nota": "volvio a escribir"})
    assert base["lead"]["estado"] == "segundo_contacto"


def test_sin_cambios_ni_nota_no_guarda_nada(base):
    with pytest.raises(ErrorValidacion, match="No hay nada que guardar"):
        seguir({"estado": "tomado", "proximo_contacto": "", "nota": "   "})
    assert base["cambios"] == [] and base["notas"] == []


@pytest.mark.parametrize("datos", [
    {"estado": "nuevo"}, {"estado": "contactado"}, {"estado": "inventado"},
    {"nota": "x" * 1001},
])
def test_estado_o_nota_no_validos_se_rechazan(base, datos):
    with pytest.raises(ErrorValidacion):
        seguir(datos)
    assert base["cambios"] == [] and base["notas"] == []


def test_el_asesor_no_gestiona_un_lead_ajeno_ni_uno_sin_tomar(base):
    with pytest.raises(ErrorValidacion, match="no es suyo"):
        seguir({"nota": "hola"}, usuario_id=OTRO_ASESOR)
    base["lead"].update(estado="nuevo", asesor_id=None)
    with pytest.raises(ErrorValidacion, match="no es suyo"):
        seguir({"nota": "hola"})
    assert base["cambios"] == [] and base["notas"] == []


def test_admin_gestiona_un_lead_ajeno_y_gerencia_no(base):
    seguir({"estado": "cita_pendiente"}, usuario_id=99, rol="admin")
    assert base["cambios"][0][2] is None            # sin filtro de asesor
    assert base["notas"][0]["usuario_id"] == 99     # queda quién lo hizo
    with pytest.raises(ErrorValidacion):
        seguir({"nota": "hola"}, usuario_id=99, rol="gerencia")


def test_si_el_lead_cambio_mientras_se_editaba_no_se_pisa(base, monkeypatch):
    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat", lambda *a, **k: None)
    with pytest.raises(ErrorValidacion, match="cambió mientras"):
        seguir({"estado": "primer_contacto", "nota": "hola"})
    assert base["notas"] == []


def test_si_el_historial_falla_se_avisa(base, monkeypatch):
    def falla(_filas):
        raise RuntimeError("sin red")
    monkeypatch.setattr(repositorios, "agregar_notas_lead", falla)
    with pytest.raises(ErrorValidacion, match="la nota se perdió"):
        seguir({"nota": "hola"})


def test_para_hoy_incluye_atrasados_y_de_hoy_el_mas_atrasado_primero(monkeypatch):
    filas = [
        lead(id=1, estado="tomado", asesor_id=ASESOR),
        lead(id=2, estado="primer_contacto", asesor_id=ASESOR, proximo_contacto="2026-11-11"),
        lead(id=3, estado="cita_pendiente", asesor_id=ASESOR, proximo_contacto="2026-11-05"),
        lead(id=4, estado="primer_contacto", asesor_id=ASESOR, proximo_contacto="2026-11-12"),
        # Cerrado con una fecha vieja: no es pendiente de nadie.
        lead(id=5, estado="descartado", asesor_id=ASESOR, proximo_contacto="2026-11-01"),
    ]
    monkeypatch.setattr(repositorios, "listar_leads_bandeja", lambda asesor_id=None: filas)
    grupos = leads_chat.listar(ASESOR, "asesor", hoy=HOY)

    assert [l["id"] for l in grupos["para_hoy"]] == [3, 2]
    assert [l["seguimiento"] for l in grupos["para_hoy"]] == ["vencido", "hoy"]
    assert grupos["para_hoy"][0]["seguimiento_texto"] == "Contacto atrasado: 5 de noviembre de 2026"
    assert [(e["estado"], [l["id"] for l in e["leads"]]) for e in grupos["etapas"]] == [
        ("tomado", [1]), ("primer_contacto", [2, 4]), ("segundo_contacto", []), ("cita_pendiente", [3])]
    assert [l["id"] for l in grupos["cerrados"]] == [5]
    assert grupos["cerrados"][0]["seguimiento"] is None


def test_el_historial_solo_se_carga_para_un_lead_tomado(monkeypatch):
    notas = [{"created_at": "2026-11-10T20:45:00+00:00", "usuario_nombre": "Luis",
              "tipo": "evento", "texto": "Estado: Primer contacto"},
             {"created_at": "2026-11-10T20:45:00+00:00", "usuario_nombre": "Luis",
              "tipo": "nota", "texto": "Llamar el lunes"}]
    monkeypatch.setattr(repositorios, "listar_notas_lead", lambda _id: notas)
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja",
                        lambda _id: lead(estado="primer_contacto", asesor_id=ASESOR))
    visto = leads_chat.obtener(1, ASESOR, "asesor")
    assert [(n["automatica"], n["texto"]) for n in visto["notas"]] == [
        (True, "Estado: Primer contacto"), (False, "Llamar el lunes")]

    monkeypatch.setattr(repositorios, "listar_notas_lead",
                        lambda _id: pytest.fail("un lead sin tomar no tiene historial"))
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja", lambda _id: lead())
    assert leads_chat.obtener(1, ASESOR, "asesor")["notas"] == []


# ------------------------------------------------------------
# Aviso push a los asesores
# ------------------------------------------------------------

@pytest.fixture
def envios(monkeypatch):
    """Tres dispositivos: uno recibe, uno está muerto (410), uno falla."""
    dispositivos = [
        {"id": 1, "usuario_id": ASESOR, "suscripcion": {"endpoint": "https://a"}},
        {"id": 2, "usuario_id": ASESOR, "suscripcion": {"endpoint": "https://b"}},
        {"id": 3, "usuario_id": OTRO_ASESOR, "suscripcion": {"endpoint": "https://c"}},
    ]
    registro = {"roles": [], "enviados": [], "desactivados": []}

    def por_rol(rol):
        registro["roles"].append(rol)
        return dispositivos

    def enviar(suscripcion, titulo, cuerpo, url="/"):
        registro["enviados"].append((suscripcion["endpoint"], titulo, cuerpo, url))
        if suscripcion["endpoint"] == "https://b":
            return {"ok": False, "estado": 410, "endpoint": "https://b", "detalle": "gone"}
        if suscripcion["endpoint"] == "https://c":
            raise RuntimeError("red caída")
        return {"ok": True, "estado": 201, "endpoint": "https://a", "detalle": "enviado"}

    monkeypatch.setattr(repositorios, "dispositivos_staff_por_rol", por_rol)
    monkeypatch.setattr(repositorios, "desactivar_dispositivo_staff",
                        lambda _id: registro["desactivados"].append(_id))
    monkeypatch.setattr(push, "enviar_a_suscripcion", enviar)
    return registro


def test_aviso_va_solo_a_asesores_y_sigue_aunque_un_dispositivo_falle(envios):
    conteo = notificaciones_staff.avisar_lead_nuevo(55)
    assert envios["roles"] == ["asesor"]
    assert conteo == {"enviados": 1, "fallidos": 1, "desactivados": 1}
    assert envios["desactivados"] == [2]            # solo el 410
    assert len(envios["enviados"]) == 3             # el error del tercero no cortó


def test_aviso_no_lleva_datos_del_cliente_y_enlaza_al_lead(envios):
    notificaciones_staff.avisar_lead_nuevo(55)
    _, titulo, cuerpo, url = envios["enviados"][0]
    assert titulo == "Nuevo lead del chat"
    assert url == "/admin/leads/55"
    assert "Ana" not in cuerpo and "300" not in cuerpo


def test_aviso_de_contado_marca_la_prioridad(envios):
    notificaciones_staff.avisar_lead_nuevo(55, contado=True)
    assert envios["enviados"][0][1] == "Prioridad: compra de contado"


def test_el_aviso_en_segundo_plano_nunca_propaga_errores(monkeypatch):
    def falla(_rol):
        raise RuntimeError("sin base")
    monkeypatch.setattr(repositorios, "dispositivos_staff_por_rol", falla)
    notificaciones_staff._avisar_sin_fallar(55, False)      # no lanza


def test_los_asesores_pueden_suscribirse():
    assert "asesor" in notificaciones_staff.ROLES_NOTIFICACIONES
    assert "encargado_sede" not in notificaciones_staff.ROLES_NOTIFICACIONES


# ------------------------------------------------------------
# Rutas
# ------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth.routes import auth_bp
    from app.publico.routes import publico_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True, VAPID_PUBLIC_KEY="BVapidPublicaDePrueba")
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.jinja_env.filters["pesos"] = lambda v: "" if v is None else f"{v:,.0f}".replace(",", ".")
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(publico_bp)
    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    return app


def cliente(app, rol, usuario_id=ASESOR):
    c = app.test_client()
    if rol:
        with c.session_transaction() as s:
            s.update(logueado=True, rol=rol, sede_id=1,
                     usuario_id=usuario_id, usuario_nombre="Luis Gomez")
    return c


@pytest.fixture
def bandeja(monkeypatch):
    filas = [lead(id=1, forma_pago="contado"),
             lead(id=2, estado="tomado", asesor_id=ASESOR, asesor_nombre="Luis Gomez")]
    monkeypatch.setattr(repositorios, "listar_leads_bandeja", lambda asesor_id=None: filas)
    monkeypatch.setattr(repositorios, "obtener_lead_bandeja",
                        lambda lead_id: next((f for f in filas if f["id"] == lead_id), None))
    monkeypatch.setattr(repositorios, "listar_notas_lead", lambda lead_id: [
        {"created_at": "2026-11-10T20:45:00+00:00", "usuario_nombre": "Luis Gomez",
         "tipo": "nota", "texto": "Llamar el lunes <b>temprano</b>"}])
    return filas


def test_bandeja_del_asesor_oculta_el_telefono_de_los_nuevos(app, bandeja):
    html = cliente(app, "asesor").get("/admin/leads").get_data(as_text=True)
    assert "Prioridad · Compra de contado" in html
    assert "/admin/leads/1/tomar" in html
    assert html.count("3001234567") == 1          # solo en el WhatsApp de su lead tomado
    assert "Activar notificaciones" in html


def test_detalle_muestra_el_contacto_solo_del_lead_propio(app, bandeja):
    c = cliente(app, "asesor")
    nuevo = c.get("/admin/leads/1").get_data(as_text=True)
    assert "3001234567" not in nuevo and "Se muestra al tomar el lead" in nuevo
    propio = c.get("/admin/leads/2").get_data(as_text=True)
    assert "3001234567" in propio and "Guardar seguimiento" in propio
    assert "/admin/leads/2/seguimiento" in propio
    # La nota es texto simple: se muestra escapada, nunca como HTML.
    assert "Llamar el lunes &lt;b&gt;temprano&lt;/b&gt;" in propio


def test_gerencia_ve_el_historial_pero_no_el_formulario(app, bandeja):
    html = cliente(app, "gerencia", usuario_id=99).get("/admin/leads/2").get_data(as_text=True)
    assert "Llamar el lunes" in html and "Guardar seguimiento" not in html


def test_lead_inexistente_vuelve_a_la_bandeja(app, bandeja):
    respuesta = cliente(app, "asesor").get("/admin/leads/999")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/admin/leads?error=no_disponible")


def test_el_error_de_la_url_es_un_codigo_no_un_texto(app, bandeja):
    c = cliente(app, "asesor")
    html = c.get("/admin/leads?error=Su+sesion+vencio,+llame+al+3000000000").get_data(as_text=True)
    assert "3000000000" not in html and 'role="alert"' not in html
    html = c.get("/admin/leads?error=ya_tomado").get_data(as_text=True)
    assert "Otro asesor ya tomó este lead." in html


@pytest.mark.parametrize("rol, esperado", [("asesor", 200), ("admin", 200), ("gerencia", 200),
                                           ("encargado_sede", 403)])
def test_quien_entra_a_la_bandeja(app, bandeja, rol, esperado):
    assert cliente(app, rol).get("/admin/leads").status_code == esperado


def test_sin_sesion_va_al_login(app):
    respuesta = app.test_client().get("/admin/leads")
    assert respuesta.status_code == 302 and "/login" in respuesta.headers["Location"]


def test_tomar_usa_la_identidad_de_la_sesion_no_la_del_formulario(app, monkeypatch):
    llamadas = []
    monkeypatch.setattr(repositorios, "tomar_lead_chat",
                        lambda lead_id, estado_requerido, cambios: llamadas.append(cambios) or {"id": lead_id})
    respuesta = cliente(app, "asesor").post("/admin/leads/1/tomar",
                                            data={"asesor_id": OTRO_ASESOR, "usuario_id": OTRO_ASESOR})
    assert respuesta.status_code == 302 and respuesta.headers["Location"].endswith("/admin/leads/1?aviso=tomado")
    assert llamadas[0]["asesor_id"] == ASESOR and llamadas[0]["asesor_nombre"] == "Luis Gomez"


@pytest.mark.parametrize("rol", ["admin", "gerencia", "encargado_sede"])
def test_otros_roles_no_pueden_tomar(app, monkeypatch, rol):
    monkeypatch.setattr(repositorios, "tomar_lead_chat",
                        lambda *a, **k: pytest.fail("no debe llegar a la base"))
    assert cliente(app, rol).post("/admin/leads/1/tomar").status_code == 403


def test_tomar_un_lead_ya_tomado_avisa_en_la_bandeja(app, monkeypatch):
    monkeypatch.setattr(repositorios, "tomar_lead_chat", lambda *a, **k: None)
    respuesta = cliente(app, "asesor").post("/admin/leads/1/tomar")
    assert respuesta.headers["Location"].endswith("/admin/leads?error=ya_tomado")


def test_seguimiento_desde_la_ruta_usa_la_identidad_de_la_sesion(app, base):
    base["lead"]["id"] = 2
    respuesta = cliente(app, "asesor").post("/admin/leads/2/seguimiento", data={
        "estado": "primer_contacto", "proximo_contacto": "", "nota": "Quedo de pasar el sabado",
        "usuario_id": OTRO_ASESOR, "asesor_id": OTRO_ASESOR})
    assert respuesta.headers["Location"].endswith("/admin/leads/2?aviso=actualizado")
    assert base["lead"]["estado"] == "primer_contacto"
    assert {n["usuario_id"] for n in base["notas"]} == {ASESOR}


def test_un_error_de_seguimiento_no_pierde_la_nota_escrita(app, base):
    respuesta = cliente(app, "asesor").post("/admin/leads/1/seguimiento", data={
        "estado": "primer_contacto", "proximo_contacto": "2020-01-01",
        "nota": "Quedo de pasar el sabado"})
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 400
    assert "no puede ser una fecha pasada" in html and "Quedo de pasar el sabado" in html
    assert base["cambios"] == [] and base["notas"] == []


@pytest.mark.parametrize("rol", ["gerencia", "encargado_sede"])
def test_otros_roles_no_registran_seguimiento(app, base, rol):
    respuesta = cliente(app, rol).post("/admin/leads/1/seguimiento", data={"nota": "hola"})
    assert respuesta.status_code == 403 and base["notas"] == []


def test_el_asesor_puede_activar_notificaciones_por_la_url_general(app, monkeypatch):
    guardadas = []
    monkeypatch.setattr(notificaciones_staff, "validar_suscripcion", lambda s: s)
    monkeypatch.setattr(repositorios, "guardar_dispositivo_staff",
                        lambda usuario_id, suscripcion: guardadas.append(usuario_id))
    respuesta = cliente(app, "asesor").post("/admin/activar-notificaciones",
                                            json={"suscripcion": {"endpoint": "https://a"}})
    assert respuesta.status_code == 200 and guardadas == [ASESOR]
    assert cliente(app, "encargado_sede").post("/admin/activar-notificaciones",
                                               json={}).status_code == 403

"""
Pruebas de la bandeja de leads del chat (/admin/leads, migración 029) y
del aviso push a los asesores.

No tocan la base ni los servicios de push: el repositorio y el envío se
reemplazan con monkeypatch. Correr desde la raíz:  python -m pytest tests/
"""

from pathlib import Path

import pytest
from flask import Flask

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import leads_chat, notificaciones_staff, push

RAIZ = Path(__file__).resolve().parent.parent
ASESOR, OTRO_ASESOR = 10, 11


def lead(**cambios):
    base = {
        "id": 1, "created_at": "2026-11-10T20:45:00+00:00",
        "nombre": "Ana Perez", "telefono": "3001234567", "correo": "ana@correo.com",
        "moto_id": None, "moto_interes": "Yamaha FZ 2019", "forma_pago": "financiado",
        "estado": "nuevo", "asesor_id": None, "asesor_nombre": None,
        "tomado_en": None, "gestionado_en": None, "motos": None,
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
    assert visto["puede_tomar"] and not visto["puede_cerrar"]


def test_asesor_ve_el_contacto_de_su_lead():
    suyo = lead(estado="tomado", asesor_id=ASESOR, asesor_nombre="Luis")
    visto = leads_chat._presentar(suyo, ASESOR, "asesor")
    assert visto["nombre"] == "Ana Perez" and visto["telefono"] == "3001234567"
    assert visto["whatsapp_url"].startswith("https://wa.me/573001234567?text=")
    assert visto["propio"] and visto["puede_cerrar"] and not visto["puede_tomar"]


@pytest.mark.parametrize("rol", ["admin", "gerencia"])
def test_admin_y_gerencia_ven_el_contacto_pero_no_toman(rol):
    visto = leads_chat._presentar(lead(), 99, rol)
    assert visto["telefono"] == "3001234567"
    assert not visto["puede_tomar"]


def test_solo_admin_cierra_un_lead_ajeno():
    ajeno = lead(estado="tomado", asesor_id=OTRO_ASESOR)
    assert leads_chat._presentar(ajeno, 99, "admin")["puede_cerrar"]
    assert not leads_chat._presentar(ajeno, 99, "gerencia")["puede_cerrar"]


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
        lead(id=5, estado="contactado", asesor_id=ASESOR),
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


def test_cerrar_exige_que_el_lead_sea_del_asesor_y_admin_cierra_cualquiera(monkeypatch):
    llamadas = []

    def cambiar(lead_id, estados_permitidos, cambios, asesor_id=None):
        llamadas.append((estados_permitidos, cambios["estado"], asesor_id))
        return {"id": lead_id}

    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat", cambiar)
    leads_chat.cerrar(1, "contactado", ASESOR, "asesor")
    leads_chat.cerrar(1, "descartado", 99, "admin")
    assert llamadas[0] == (["tomado", "contactado", "descartado"], "contactado", ASESOR)
    assert llamadas[1][1:] == ("descartado", None)


@pytest.mark.parametrize("estado, rol", [
    ("nuevo", "asesor"), ("tomado", "asesor"), (None, "asesor"), ("vendido", "admin"),
    ("contactado", "gerencia"),
])
def test_cerrar_rechaza_estados_y_roles_no_validos(monkeypatch, estado, rol):
    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat",
                        lambda *a, **k: pytest.fail("no debe llegar a la base"))
    with pytest.raises(ErrorValidacion):
        leads_chat.cerrar(1, estado, ASESOR, rol)


def test_cerrar_un_lead_ajeno_falla(monkeypatch):
    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat", lambda *a, **k: None)
    with pytest.raises(ErrorValidacion):
        leads_chat.cerrar(1, "contactado", ASESOR, "asesor")


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
    assert "3001234567" in propio and "Marcar contactado" in propio


def test_lead_inexistente_vuelve_a_la_bandeja(app, bandeja):
    respuesta = cliente(app, "asesor").get("/admin/leads/999")
    assert respuesta.status_code == 302 and "/admin/leads?error=" in respuesta.headers["Location"]


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
    assert "/admin/leads?error=Otro" in respuesta.headers["Location"]


def test_cerrar_desde_la_ruta(app, monkeypatch):
    llamadas = []
    monkeypatch.setattr(repositorios, "cambiar_estado_lead_chat",
                        lambda lead_id, estados_permitidos, cambios, asesor_id=None:
                        llamadas.append((cambios["estado"], asesor_id)) or {"id": lead_id})
    respuesta = cliente(app, "asesor").post("/admin/leads/2/estado", data={"estado": "contactado"})
    assert respuesta.headers["Location"].endswith("/admin/leads/2?aviso=actualizado")
    assert llamadas == [("contactado", ASESOR)]
    assert cliente(app, "gerencia").post("/admin/leads/2/estado",
                                         data={"estado": "contactado"}).status_code == 403


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

"""
Pruebas de "Mi espacio" del asesor (/admin/mi-espacio) y del destino
después del login.

No tocan la base: el repositorio se reemplaza con monkeypatch.
Correr desde la raíz:  python -m pytest tests/
"""

from datetime import date
from pathlib import Path

import pytest
from flask import Flask

from app.auth import destino
from app.db import repositorios
from app.servicios import espacio_asesor

RAIZ = Path(__file__).resolve().parent.parent
ASESOR = 10
MARTES = date(2026, 11, 10)     # semana del lunes 9 al domingo 15


# ------------------------------------------------------------
# La semana: lunes a domingo
# ------------------------------------------------------------

@pytest.mark.parametrize("hoy", [date(2026, 11, 9), MARTES, date(2026, 11, 15)])
def test_semana_actual_va_de_lunes_a_domingo(hoy):
    assert espacio_asesor.semana_de(None, hoy) == (date(2026, 11, 9), date(2026, 11, 15))


def test_cualquier_dia_de_una_semana_pasada_lleva_a_su_lunes():
    assert espacio_asesor.semana_de("2026-11-05", MARTES) == (date(2026, 11, 2), date(2026, 11, 8))


@pytest.mark.parametrize("cruda", ["2026-12-25", "ayer", "", "2026-13-40", "1; drop table", None])
def test_semana_invalida_o_futura_cae_en_la_actual(cruda):
    assert espacio_asesor.semana_de(cruda, MARTES) == (date(2026, 11, 9), date(2026, 11, 15))


def test_periodo_legible():
    assert espacio_asesor._periodo(date(2026, 11, 9), date(2026, 11, 15)) == "Del 9 al 15 de noviembre de 2026"
    assert (espacio_asesor._periodo(date(2026, 11, 30), date(2026, 12, 6))
            == "Del 30 de noviembre al 6 de diciembre de 2026")


# ------------------------------------------------------------
# El resumen
# ------------------------------------------------------------

@pytest.fixture
def base(monkeypatch):
    """Repositorio falso. Devuelve las llamadas: (tabla, asesor_id, desde, hasta)."""
    llamadas = []

    def ventas(asesor_id, desde, hasta):
        llamadas.append(("ventas", asesor_id, desde, hasta))
        return [
            {"id": 1, "created_at": "2026-11-10T20:45:00+00:00", "descripcion": "Yamaha FZ 2019",
             "placa": "ABC12D", "verificada": True, "estado": "activa", "precio_venta": 7500000},
            {"id": 2, "created_at": "2026-11-11T15:00:00+00:00", "descripcion": "Honda CB 2020",
             "placa": "XYZ98A", "verificada": False, "estado": "anulada"},
        ]

    def compras(asesor_id, desde, hasta):
        llamadas.append(("compras", asesor_id, desde, hasta))
        return [{"id": 3, "created_at": "2026-11-12T15:00:00+00:00", "descripcion": "Bajaj Pulsar 2018",
                 "placa": "QWE45R", "verificada": False, "precio_compra": 4000000}]

    def permutas(asesor_id, desde, hasta):
        llamadas.append(("permutas", asesor_id, desde, hasta))
        return [{"id": 4, "created_at": "2026-11-13T15:00:00+00:00",
                 "descripcion_entrante": "AKT 125 2017", "descripcion_saliente": "Suzuki GN 2021"}]

    def leads(asesor_id=None):
        llamadas.append(("leads", asesor_id))
        nuevo = {"id": 1, "created_at": "2026-11-10T20:45:00+00:00", "nombre": "Ana Perez",
                 "telefono": "3001234567", "correo": None, "moto_id": None, "moto_interes": "FZ",
                 "forma_pago": "financiado", "estado": "nuevo", "asesor_id": None,
                 "asesor_nombre": None, "tomado_en": None, "gestionado_en": None, "motos": None}
        nuevos = [dict(nuevo, id=i) for i in range(1, 8)]
        nuevos[6]["forma_pago"] = "contado"
        suyo = dict(nuevo, asesor_id=ASESOR)
        return nuevos + [
            dict(suyo, id=20, estado="tomado"),
            # Fecha del lunes 9: el martes 10 ya está atrasado.
            dict(suyo, id=21, estado="primer_contacto", proximo_contacto="2026-11-09"),
            # Ya le escribió y no programó fecha: antes desaparecía de la portada.
            dict(suyo, id=22, estado="primer_contacto"),
            dict(suyo, id=23, estado="cita_pendiente", proximo_contacto="2026-11-20"),
            dict(suyo, id=30, estado="vendido"),
            dict(suyo, id=31, estado="descartado"),
            dict(suyo, id=32, estado="descartado"),
        ] + [dict(suyo, id=40 + i, estado="segundo_contacto") for i in range(7)]

    monkeypatch.setattr(repositorios, "ventas_de_asesor_en_rango", ventas)
    monkeypatch.setattr(repositorios, "compras_de_asesor_en_rango", compras)
    monkeypatch.setattr(repositorios, "permutas_de_asesor_en_rango", permutas)
    monkeypatch.setattr(repositorios, "listar_leads_bandeja", leads)
    return llamadas


def test_resumen_cuenta_lo_del_asesor_en_la_semana_cortada_en_hora_de_colombia(base):
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)

    for tabla, asesor_id, desde, hasta in [ll for ll in base if ll[0] != "leads"]:
        assert asesor_id == ASESOR
        assert desde == "2026-11-09T00:00:00-05:00"     # lunes 00:00 Colombia
        assert hasta == "2026-11-16T00:00:00-05:00"     # lunes siguiente (domingo completo)
    assert ("leads", ASESOR) in base

    assert len(datos["ventas"]) == 1                    # la anulada no cuenta
    assert len(datos["compras"]) == 1 and len(datos["permutas"]) == 1
    assert datos["ventas"][0] == {"cuando": "10 de noviembre, 3:45 p. m.", "moto": "Yamaha FZ 2019",
                                  "placa": "ABC12D", "verificada": True}
    assert datos["permutas"][0]["saliente"] == "Suzuki GN 2021"
    assert datos["periodo"] == "Del 9 al 15 de noviembre de 2026"


def test_resumen_no_lleva_ningun_valor_en_pesos(base):
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    operaciones = str([datos["ventas"], datos["compras"], datos["permutas"]])
    assert "7500000" not in operaciones and "4000000" not in operaciones
    assert "precio" not in operaciones


def test_navegacion_entre_semanas_sin_ir_al_futuro(base):
    actual = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    assert actual["es_semana_actual"] and actual["semana_siguiente"] is None
    assert actual["semana_anterior"] == "2026-11-02"

    pasada = espacio_asesor.resumen(ASESOR, "2026-11-04", hoy=MARTES)
    assert not pasada["es_semana_actual"]
    assert pasada["semana_anterior"] == "2026-10-26" and pasada["semana_siguiente"] == "2026-11-09"


def test_leads_en_portada_contado_primero_y_con_tope(base):
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    assert datos["total_leads_nuevos"] == 7 and datos["total_leads_en_gestion"] == 11
    assert len(datos["leads_nuevos"]) == espacio_asesor.LEADS_EN_PORTADA
    assert datos["leads_nuevos"][0]["prioridad"]                    # el de contado
    assert all(l["telefono"] is None for l in datos["leads_nuevos"])  # sin contacto hasta tomarlo


def test_portada_pone_arriba_lo_de_hoy(base):
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    assert [l["id"] for l in datos["leads_para_hoy"]] == [21]
    assert datos["leads_para_hoy"][0]["seguimiento"] == "vencido"
    # Son suyos: aquí sí va el contacto, para escribirle de una vez.
    assert datos["leads_para_hoy"][0]["whatsapp_url"]


def test_portada_lista_todos_sus_clientes_por_etapa(base):
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    etapas = {e["estado"]: e for e in datos["etapas_seguimiento"]}
    assert list(etapas) == ["tomado", "primer_contacto", "segundo_contacto", "cita_pendiente"]
    assert [e["titulo"] for e in datos["etapas_seguimiento"]][:2] == ["Por contactar", "Primer contacto"]

    assert [l["id"] for l in etapas["tomado"]["leads"]] == [20]
    # El 21 ya sale en "para hoy": cuenta en la etapa pero no se repite.
    assert etapas["primer_contacto"]["total"] == 2
    assert [l["id"] for l in etapas["primer_contacto"]["leads"]] == [22]
    assert [l["id"] for l in etapas["cita_pendiente"]["leads"]] == [23]
    assert etapas["cita_pendiente"]["leads"][0]["seguimiento_texto"] == (
        "Próximo contacto: 20 de noviembre de 2026")

    # Con tope por etapa: el resto se ve en la bandeja.
    segundo = etapas["segundo_contacto"]
    assert segundo["total"] == 7 and segundo["sin_listar"] == 2
    assert len(segundo["leads"]) == espacio_asesor.CLIENTES_POR_ETAPA

    # Los cerrados no se listan, solo se cuentan.
    listados = {l["id"] for e in datos["etapas_seguimiento"] for l in e["leads"]}
    assert not listados & {30, 31, 32}
    assert (datos["total_leads_vendidos"], datos["total_leads_descartados"]) == (1, 2)


def test_portada_sin_clientes_lo_dice(base, monkeypatch):
    monkeypatch.setattr(repositorios, "listar_leads_bandeja", lambda asesor_id=None: [])
    datos = espacio_asesor.resumen(ASESOR, None, hoy=MARTES)
    assert datos["total_leads_en_gestion"] == 0
    assert all(e["total"] == 0 and e["leads"] == [] for e in datos["etapas_seguimiento"])


# ------------------------------------------------------------
# Destino después del login
# ------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth import routes as auth_routes
    from app.publico.routes import publico_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True, RATELIMIT_ENABLED=False,
                      VAPID_PUBLIC_KEY="BVapidPublicaDePrueba")
    app.jinja_env.globals["csrf_token"] = lambda: "token"
    app.jinja_env.filters["pesos"] = lambda v: "" if v is None else f"{v:,.0f}".replace(",", ".")
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(publico_bp)
    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    return app


@pytest.mark.parametrize("rol, esperado", [
    ("asesor", "/admin/mi-espacio"), ("gerencia", "/admin/gerencia"),
    ("admin", "/admin/"), ("encargado_sede", "/admin/"),
])
def test_cada_rol_aterriza_en_su_portada(app, rol, esperado):
    with app.test_request_context("/"):
        assert destino.destino_tras_login(rol).rstrip("/") == esperado.rstrip("/")


@pytest.mark.parametrize("rol", ["asesor", "admin", "gerencia"])
def test_quien_venia_a_un_lead_vuelve_al_lead(app, rol):
    with app.test_request_context("/"):
        assert destino.destino_tras_login(rol, "/admin/leads/55") == "/admin/leads/55"
        assert destino.destino_tras_login(rol, "/admin/leads") == "/admin/leads"


def test_un_rol_sin_bandeja_no_es_enviado_a_los_leads(app):
    with app.test_request_context("/"):
        assert "leads" not in destino.destino_tras_login("encargado_sede", "/admin/leads/55")


@pytest.mark.parametrize("malo", [
    "https://malo.example/admin/leads/1", "//malo.example", "/admin/usuarios",
    "/admin/leads/1/tomar", "/admin/leads/../usuarios", "/admin/leads/1?x=//malo", 5, None, "",
])
def test_solo_se_acepta_una_ruta_de_la_bandeja_como_destino(app, malo):
    with app.test_request_context("/"):
        assert destino.destino_tras_login("asesor", malo) == "/admin/mi-espacio"
        destino.recordar_destino(malo)
        from flask import session
        assert destino.CLAVE_DESTINO not in session


def test_tocar_el_aviso_sin_sesion_lleva_al_lead_tras_el_login(app, monkeypatch):
    from app.auth import routes as auth_routes
    monkeypatch.setattr(auth_routes, "autenticar", lambda u, p: {
        "id": ASESOR, "usuario": "luis", "nombre_completo": "Luis Gomez",
        "rol": "asesor", "sede_id": 1, "whatsapp": None})

    c = app.test_client()
    sin_sesion = c.get("/admin/leads/55")
    assert sin_sesion.status_code == 302 and "/login" in sin_sesion.headers["Location"]

    entrar = c.post("/login", data={"usuario": "luis", "password": "x"})
    assert entrar.headers["Location"] == "/admin/leads/55"

    # El destino se usa una sola vez: el siguiente login va a Mi espacio.
    c.get("/logout")
    entrar = c.post("/login", data={"usuario": "luis", "password": "x"})
    assert entrar.headers["Location"] == "/admin/mi-espacio"


def test_otra_ruta_sin_sesion_no_se_recuerda(app, monkeypatch):
    from app.auth import routes as auth_routes
    monkeypatch.setattr(auth_routes, "autenticar", lambda u, p: {
        "id": ASESOR, "usuario": "luis", "nombre_completo": "Luis Gomez",
        "rol": "asesor", "sede_id": 1, "whatsapp": None})
    c = app.test_client()
    c.get("/admin/usuarios")
    assert c.post("/login", data={"usuario": "luis", "password": "x"}).headers["Location"] == "/admin/mi-espacio"


# ------------------------------------------------------------
# La ruta
# ------------------------------------------------------------

def cliente(app, rol, usuario_id=ASESOR):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(logueado=True, rol=rol, sede_id=1, usuario_id=usuario_id, usuario_nombre="Luis Gomez")
    return c


def test_portada_del_asesor_muestra_conteos_y_nunca_pesos(app, base):
    html = cliente(app, "asesor").get("/admin/mi-espacio").get_data(as_text=True)
    assert "Mi espacio" in html and "Yamaha FZ 2019" in html and "Suzuki GN 2021" in html
    assert "Leads disponibles" in html and "/admin/leads/7/tomar" in html
    assert "7.500.000" not in html and "7500000" not in html and "4000000" not in html
    # El contacto solo aparece en el WhatsApp de los clientes suyos que se
    # listan (1 para hoy + 1 + 1 + 5 + 1 por etapa); nunca en los leads
    # disponibles, que no son de nadie.
    assert html.count("3001234567") == 9
    assert "Para contactar hoy" in html and "Mis clientes en seguimiento" in html
    assert 'href="#mis-clientes"' in html and 'id="mis-clientes"' in html
    assert "Ver los 7 de segundo contacto" in html and "/admin/leads#etapa-segundo_contacto" in html
    assert "Cerrados: 1 vendidos · 2 descartados" in html


def test_el_asesor_es_el_de_la_sesion_aunque_la_url_diga_otro(app, base):
    cliente(app, "asesor").get("/admin/mi-espacio?usuario_id=99&asesor_id=99&semana=2026-11-03")
    consultas = [ll for ll in base if ll[0] in ("ventas", "compras", "permutas")]
    assert consultas and all(ll[1] == ASESOR for ll in consultas)
    assert consultas[0][2] == "2026-11-02T00:00:00-05:00"


@pytest.mark.parametrize("rol", ["admin", "gerencia", "encargado_sede"])
def test_solo_el_asesor_entra_a_mi_espacio(app, base, rol):
    assert cliente(app, rol).get("/admin/mi-espacio").status_code == 403


# ------------------------------------------------------------
# El asesor no registra compras desde el panel
# ------------------------------------------------------------

def test_el_asesor_no_tiene_la_ruta_de_compra_que_antes_usaba(app):
    c = cliente(app, "asesor")
    assert c.get("/admin/comprar").status_code == 404
    assert c.post("/admin/comprar", data={"marca": "Yamaha"}).status_code == 404


def test_el_asesor_no_entra_a_nueva_compra_ni_la_ve_en_el_menu(app, base):
    c = cliente(app, "asesor")
    assert c.get("/admin/compras/nueva").status_code == 403
    html = c.get("/admin/mi-espacio").get_data(as_text=True)
    assert "Comprar moto" not in html and "Nueva compra" not in html
    assert "/admin/comprar" not in html and "/admin/compras/nueva" not in html
    # Sus compras (las que registró un encargado a su nombre) sí las sigue viendo.
    assert "Mis compras" in html and "Bajaj Pulsar 2018" in html

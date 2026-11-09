"""
Pruebas del resumen semanal de gerencia (reportes.resumen_semanal) y de
su ruta /admin/gerencia/resumen-semanal.

No tocan la base: las lecturas del repositorio se reemplazan con
monkeypatch. Correr desde la raíz del proyecto:  python -m pytest tests/
"""

from datetime import date
from pathlib import Path

import pytest
from flask import Flask, redirect

from app.db import repositorios
from app.servicios import reportes

RAIZ = Path(__file__).resolve().parent.parent


def venta(precio, asesor="Ana", sede_id=1, sede="Norte", estado="activa"):
    return {"estado": estado, "precio_venta": precio, "asesor_nombre": asesor,
            "sede_id": sede_id, "sedes": {"nombre": sede} if sede else None}


# ------------------------------------------------------------
#  Agregación pura
# ------------------------------------------------------------

def test_agrega_los_tres_bloques():
    ventas = [
        venta(10_000_000, "Ana", 1, "Norte"),
        venta(8_000_000, "Ana", 1, "Norte"),
        venta(12_000_000, "Beto", 2, "Sur"),
    ]
    compras = [{"precio_compra": 5_000_000}, {"precio_compra": 7_000_000}]
    permutas = [{"id": 1}, {"id": 2}, {"id": 3}]

    r = reportes.agregar_resumen(ventas, compras, permutas)

    assert r["ventas"] == {"cantidad": 3, "monto": 30_000_000, "sin_precio": 0}
    assert r["por_sede"] == [
        {"sede": "Norte", "cantidad": 2, "monto": 18_000_000},
        {"sede": "Sur", "cantidad": 1, "monto": 12_000_000},
    ]
    assert r["top_asesores"] == [
        {"asesor_nombre": "Ana", "cantidad": 2, "monto": 18_000_000},
        {"asesor_nombre": "Beto", "cantidad": 1, "monto": 12_000_000},
    ]
    assert r["compras"] == {"cantidad": 2, "monto": 12_000_000, "sin_precio": 0}
    assert r["permutas"] == {"cantidad": 3}


def test_anuladas_no_cuentan_en_ningun_bloque_de_ventas():
    r = reportes.agregar_resumen(
        [venta(10_000_000), venta(9_000_000, "Beto", 2, "Sur", estado="anulada")], [], [])

    assert r["ventas"]["cantidad"] == 1 and r["ventas"]["monto"] == 10_000_000
    assert [s["sede"] for s in r["por_sede"]] == ["Norte"]
    assert [a["asesor_nombre"] for a in r["top_asesores"]] == ["Ana"]


def test_venta_sin_precio_cuenta_en_cantidad_pero_no_en_monto():
    r = reportes.agregar_resumen([venta(10_000_000), venta(None)], [], [])

    assert r["ventas"] == {"cantidad": 2, "monto": 10_000_000, "sin_precio": 1}
    assert r["top_asesores"][0] == {"asesor_nombre": "Ana", "cantidad": 2, "monto": 10_000_000}


def test_compra_sin_precio_cuenta_pero_no_suma():
    r = reportes.agregar_resumen([], [{"precio_compra": 4_000_000}, {"precio_compra": None}], [])
    assert r["compras"] == {"cantidad": 2, "monto": 4_000_000, "sin_precio": 1}


def test_sede_y_asesor_faltantes_tienen_etiqueta():
    r = reportes.agregar_resumen([venta(1_000_000, asesor=None, sede_id=None, sede=None)], [], [])
    assert r["por_sede"][0]["sede"] == "Sin sede"
    assert r["top_asesores"][0]["asesor_nombre"] == "Sin asesor"


def test_top_asesores_corta_en_cinco_y_desempata_por_monto():
    ventas = [venta(1_000_000, f"Asesor {i}") for i in range(6)]
    ventas += [venta(5_000_000, "Zoe"), venta(1_000_000, "Zoe")]   # 2 ventas: primera
    ventas.append(venta(9_000_000, "Yago"))                         # 1 venta, mayor monto

    top = reportes.agregar_resumen(ventas, [], [])["top_asesores"]

    assert len(top) == reportes.TOP_ASESORES
    assert [a["asesor_nombre"] for a in top[:2]] == ["Zoe", "Yago"]
    assert [a["asesor_nombre"] for a in top[2:]] == ["Asesor 0", "Asesor 1", "Asesor 2"]


def test_semana_vacia():
    r = reportes.agregar_resumen([], [], [])
    assert r["ventas"] == {"cantidad": 0, "monto": 0, "sin_precio": 0}
    assert r["por_sede"] == [] and r["top_asesores"] == []
    assert r["compras"]["cantidad"] == 0 and r["permutas"] == {"cantidad": 0}


# ------------------------------------------------------------
#  Rango de la semana
# ------------------------------------------------------------

@pytest.mark.parametrize("hoy", [
    date(2026, 11, 9),    # lunes: la semana que terminó ayer
    date(2026, 11, 12),   # jueves
    date(2026, 11, 15),   # domingo: la actual aún no terminó
])
def test_ultima_semana_completa(hoy):
    assert reportes.ultima_semana_completa(hoy) == (date(2026, 11, 2), date(2026, 11, 8))


def test_corta_los_dias_en_hora_de_colombia(monkeypatch):
    rangos = []

    def leer(desde, hasta):
        rangos.append((desde, hasta))
        return []

    for nombre in ("resumen_ventas_en_rango", "resumen_compras_en_rango",
                   "resumen_permutas_en_rango"):
        monkeypatch.setattr(repositorios, nombre, leer)

    r = reportes.resumen_semanal(date(2026, 11, 2), date(2026, 11, 8))

    # Domingo inclusivo: el fin es el lunes siguiente a las 00:00 de Bogotá (exclusivo).
    assert rangos == [("2026-11-02T00:00:00-05:00", "2026-11-09T00:00:00-05:00")] * 3
    assert r["periodo"] == "Del 2 de noviembre de 2026 al 8 de noviembre de 2026"


# ------------------------------------------------------------
#  Ruta
# ------------------------------------------------------------

URL = "/admin/gerencia/resumen-semanal"


@pytest.fixture
def app(monkeypatch):
    from app.admin import routes as admin_routes
    from app.auth.routes import auth_bp

    app = Flask(__name__, template_folder=str(RAIZ / "app" / "templates"),
                static_folder=str(RAIZ / "static"))
    app.config.update(SECRET_KEY="test", TESTING=True)
    app.jinja_env.filters["pesos"] = lambda v: "" if v is None else f"{v:,.0f}".replace(",", ".")
    app.register_blueprint(admin_routes.admin_bp)
    app.register_blueprint(auth_bp)

    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado", lambda: None)
    monkeypatch.setattr(repositorios, "resumen_ventas_en_rango",
                        lambda d, h: [venta(10_000_000, "Ana Asesora", 1, "Av 1 de Mayo"),
                                      venta(None, "Beto", 2, "Sur")])
    monkeypatch.setattr(repositorios, "resumen_compras_en_rango",
                        lambda d, h: [{"precio_compra": 6_500_000}])
    monkeypatch.setattr(repositorios, "resumen_permutas_en_rango", lambda d, h: [{"id": 1}])
    return app


def cliente_con_rol(app, rol):
    cliente = app.test_client()
    if rol:
        with cliente.session_transaction() as s:
            s.update(logueado=True, rol=rol, sede_id=1, usuario_id=1, usuario_nombre="Prueba")
    return cliente


@pytest.mark.parametrize("rol", ["gerencia", "admin"])
def test_gerencia_y_admin_ven_el_resumen(app, rol):
    respuesta = cliente_con_rol(app, rol).get(URL)
    html = respuesta.get_data(as_text=True)

    assert respuesta.status_code == 200
    assert "Av 1 de Mayo" in html and "Ana Asesora" in html
    assert "$10.000.000" in html and "$6.500.000" in html
    assert "1 venta sin precio cargado" in html


@pytest.mark.parametrize("rol", ["asesor", "encargado_sede"])
def test_otros_roles_reciben_403(app, rol):
    assert cliente_con_rol(app, rol).get(URL).status_code == 403


def test_sin_sesion_va_al_login(app):
    respuesta = cliente_con_rol(app, None).get(URL)
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/login")


def test_usuario_deshabilitado_no_llega_a_la_vista(app, monkeypatch):
    from app.admin import routes as admin_routes

    monkeypatch.setattr(admin_routes, "verificar_usuario_habilitado",
                        lambda: redirect("/login"))
    monkeypatch.setattr(reportes, "resumen_semanal",
                        lambda *a: pytest.fail("no debía calcular el resumen"))

    respuesta = cliente_con_rol(app, "gerencia").get(URL)
    assert respuesta.status_code == 302

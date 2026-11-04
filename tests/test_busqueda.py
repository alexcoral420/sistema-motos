"""Exportación CSV del inventario del panel (app/servicios/busqueda.py)."""

import csv
import io

from app.db import repositorios
from app.servicios import busqueda, sedes


def _leer(contenido: bytes):
    assert contenido.startswith(b"\xef\xbb\xbf")  # BOM para Excel
    return list(csv.reader(io.StringIO(contenido.decode("utf-8-sig"))))


def test_csv_columnas_y_filas():
    filas = [{"placa": "ABC12D", "modelo": "NKD 125", "anio": 2020, "precio": 4500000},
             {"placa": "XYZ98E", "modelo": "Pulsar", "anio": None, "precio": None}]
    assert _leer(busqueda.generar_csv(filas)) == [
        ["placa", "modelo", "año", "precio"],
        ["ABC12D", "NKD 125", "2020", "4500000"],
        ["XYZ98E", "Pulsar", "", ""],
    ]


def test_csv_neutraliza_formulas():
    filas = [{"placa": "=HYPERLINK(1)", "modelo": "@SUM(A1)", "anio": 2021, "precio": 1}]
    fila = _leer(busqueda.generar_csv(filas))[1]
    assert fila[0] == "'=HYPERLINK(1)"
    assert fila[1] == "'@SUM(A1)"


def test_exportar_aplica_filtros_validados(monkeypatch):
    llamadas = []
    monkeypatch.setattr(repositorios, "motos_para_exportar",
                        lambda estado, sede: llamadas.append((estado, sede)) or [])
    monkeypatch.setattr(sedes, "ids_validos", lambda: {"1", "2"})

    _, nombre = busqueda.exportar_csv({"estado": "por_publicar", "sede": "2"})
    busqueda.exportar_csv({"estado": "inventado", "sede": "99"})

    assert llamadas == [("por_publicar", "2"), (None, None)]
    assert nombre.startswith("inventario_") and nombre.endswith(".csv")
    assert len(nombre) == len("inventario_AAAAMMDD.csv")


def test_traer_todas_pasa_el_corte_de_1000():
    total = 2345

    class Consulta:
        def range(self, desde, hasta):
            self.desde, self.hasta = desde, hasta
            return self

        def execute(self):
            class R:
                pass
            r = R()
            r.data = [{"id": i} for i in range(self.desde, min(self.hasta + 1, total))]
            return r

    filas = repositorios._traer_todas(Consulta)
    assert len(filas) == total

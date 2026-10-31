from app.servicios.avaluo import _estimar


def comparable(anio, precio, km=None):
    return {"anio": anio, "precio": precio, "km": km}


def test_sin_comparables_devuelve_sin_datos():
    r = _estimar([], anio=2022, km=10000)
    assert r == {"sin_datos": True}


def test_menos_km_estima_mas_alto_que_mas_km():
    comps = [
        comparable(2022, 8_000_000, km=40000),
        comparable(2022, 9_000_000, km=30000),
        comparable(2022, 10_000_000, km=20000),
        comparable(2022, 11_000_000, km=10000),
    ]
    poco  = _estimar(comps, anio=2022, km=10000)
    mucho = _estimar(comps, anio=2022, km=40000)
    assert poco["estimado"] > mucho["estimado"]

def test_estimado_siempre_dentro_del_rango():
    comps = [
        comparable(2022, 7_000_000, km=50000),
        comparable(2022, 8_000_000, km=38000),
        comparable(2022, 9_000_000, km=25000),
        comparable(2022, 10_000_000, km=15000),
        comparable(2022, 11_000_000, km=8000),
    ]
    # Pase el km que pase, el estimado NUNCA debe salirse del rango.
    for km in [5000, 20000, 35000, 50000, 80000, None]:
        r = _estimar(comps, anio=2022, km=km)
        assert r["rango_min"] <= r["estimado"] <= r["rango_max"], f"se escapó con km={km}"
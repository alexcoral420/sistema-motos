"""Tests de la validación de recordatorios (servicio puro, sin Supabase)."""

import base64
from datetime import date, timedelta

import pytest

from app.servicios import recordatorios
from app.seguridad.validadores import ErrorValidacion

HOY = date(2026, 10, 31)


def _b64(n):
    return base64.urlsafe_b64encode(b"\x04" * n).rstrip(b"=").decode()


def _suscripcion(endpoint="https://fcm.googleapis.com/fcm/send/abc123"):
    return {"endpoint": endpoint, "keys": {"p256dh": _b64(65), "auth": _b64(16)}}


def _solicitud(**cambios):
    datos = {
        "fecha_soat": "2027-03-15",
        "fecha_tecno": None,
        "placa": None,
        "acepta_politica": True,
        "suscripcion": _suscripcion(),
    }
    datos.update(cambios)
    return datos


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(recordatorios, "_hoy", lambda: HOY)


def test_solicitud_valida():
    limpio = recordatorios.validar_solicitud(_solicitud(placa=" abc-12d "))
    assert limpio["fecha_soat"] == date(2027, 3, 15)
    assert limpio["fecha_tecno"] is None
    assert limpio["placa"] == "ABC12D"


def test_placa_vieja_sin_letra_final():
    assert recordatorios.validar_solicitud(_solicitud(placa="abc12"))["placa"] == "ABC12"


@pytest.mark.parametrize("placa", ["AB12C", "ABC123", "123ABC", "ABCD12E"])
def test_placa_invalida(placa):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(placa=placa))


def test_exige_alguna_fecha():
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(fecha_soat=None, fecha_tecno=""))


def test_solo_tecno_vale():
    limpio = recordatorios.validar_solicitud(_solicitud(fecha_soat=None, fecha_tecno="2027-01-10"))
    assert limpio["fecha_tecno"] == date(2027, 1, 10)


@pytest.mark.parametrize("fecha", [
    "15/03/2027", "2027-02-30", 20270315,
    (HOY - timedelta(days=366)).isoformat(),
    (HOY + timedelta(days=731)).isoformat(),
])
def test_fecha_invalida_o_fuera_de_rango(fecha):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(fecha_soat=fecha))


@pytest.mark.parametrize("acepta", [False, None, "true", 1])
def test_exige_consentimiento_explicito(acepta):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(acepta_politica=acepta))


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/x",
    "https://updates.push.services.mozilla.com/wpush/v2/x",
    "https://wns2-by3p.notify.windows.com/w/?token=x",
    "https://web.push.apple.com/x",
])
def test_endpoints_de_servicios_de_push(endpoint):
    recordatorios.validar_solicitud(_solicitud(suscripcion=_suscripcion(endpoint)))


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",            # sin https
    "https://evil.com/fcm.googleapis.com",             # host ajeno
    "https://fcm.googleapis.com.evil.com/x",           # sufijo engañoso
    "https://evilfcm.googleapis.com.ru/x",
    "https://localhost/x",
    "https://169.254.169.254/latest/meta-data",
    "https://fcm.googleapis.com:8443/x",               # puerto raro
    "https://user@fcm.googleapis.com/x",               # credenciales en la URL
    "https://fcm.googleapis.com/" + "x" * 1000,        # demasiado largo
])
def test_rechaza_endpoints_no_permitidos(endpoint):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(suscripcion=_suscripcion(endpoint)))


@pytest.mark.parametrize("claves", [
    {"p256dh": _b64(64), "auth": _b64(16)},
    {"p256dh": _b64(65), "auth": _b64(15)},
    {"p256dh": "no es base64!", "auth": _b64(16)},
    {"auth": _b64(16)},
    "texto",
])
def test_rechaza_claves_invalidas(claves):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(_solicitud(suscripcion={
            "endpoint": "https://fcm.googleapis.com/fcm/send/x", "keys": claves}))


def test_suscripcion_se_reconstruye_sin_campos_extra():
    sus = _suscripcion()
    sus["expirationTime"] = None
    sus["keys"]["extra"] = "x"
    sus["otro"] = {"lo": "que sea"}
    limpio = recordatorios.validar_solicitud(_solicitud(suscripcion=sus))["suscripcion"]
    assert set(limpio) == {"endpoint", "keys"}
    assert set(limpio["keys"]) == {"p256dh", "auth"}


@pytest.mark.parametrize("datos", [None, [], "texto"])
def test_cuerpo_no_objeto(datos):
    with pytest.raises(ErrorValidacion):
        recordatorios.validar_solicitud(datos)


def test_crear_guarda_hash_y_devuelve_token(monkeypatch):
    guardado = {}
    monkeypatch.setattr(recordatorios.repositorios, "obtener_politica_vigente",
                        lambda: {"id": 3, "version": "v2"})
    monkeypatch.setattr(recordatorios.repositorios, "crear_recordatorio",
                        lambda registro: guardado.update(registro))

    token = recordatorios.crear(_solicitud(placa="abc12d"))

    assert token and token not in str(guardado)
    assert guardado["token_hash"] == recordatorios.hash_token(token)
    assert guardado["fecha_soat"] == "2027-03-15"
    assert guardado["placa"] == "ABC12D"
    assert guardado["politica_id"] == 3 and guardado["version_politica"] == "v2"


def test_crear_no_guarda_si_es_invalido(monkeypatch):
    monkeypatch.setattr(recordatorios.repositorios, "crear_recordatorio",
                        lambda registro: pytest.fail("no debió guardar"))
    with pytest.raises(ErrorValidacion):
        recordatorios.crear(_solicitud(acepta_politica=False))

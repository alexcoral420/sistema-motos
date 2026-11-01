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


# ---------------------------------------------------------------- envío

class _Respuesta:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


@pytest.fixture
def envio(monkeypatch):
    """Config VAPID falsa y repositorio espiado; devuelve el registro de llamadas."""
    monkeypatch.setattr(recordatorios.Config, "VAPID_PRIVATE_KEY", "clave")
    monkeypatch.setattr(recordatorios.Config, "VAPID_SUBJECT", "mailto:x@y.co")
    llamadas = {"webpush": [], "desactivar": []}

    def desactivar(endpoint, actualizado_en):
        llamadas["desactivar"].append(endpoint)
        return 2
    monkeypatch.setattr(recordatorios.repositorios, "desactivar_recordatorios_por_endpoint", desactivar)
    return llamadas


def _con_webpush(monkeypatch, llamadas, estado):
    def falso(**kwargs):
        llamadas["webpush"].append(kwargs)
        if estado >= 400:
            raise recordatorios.WebPushException("error", response=_Respuesta(estado))
        return _Respuesta(estado)
    monkeypatch.setattr(recordatorios, "webpush", falso)


def test_envio_exitoso(monkeypatch, envio):
    _con_webpush(monkeypatch, envio, 201)
    r = recordatorios.enviar_push({"suscripcion": _suscripcion()}, "T", "C", "/x")
    assert r == {"ok": True, "estado": 201, "desactivados": 0, "detalle": "enviado"}
    kwargs = envio["webpush"][0]
    assert kwargs["vapid_claims"] == {"sub": "mailto:x@y.co"}
    assert kwargs["vapid_private_key"] == "clave"
    assert '"title": "T"' in kwargs["data"] and '"url": "/x"' in kwargs["data"]
    assert envio["desactivar"] == []


@pytest.mark.parametrize("estado", [404, 410])
def test_suscripcion_muerta_desactiva(monkeypatch, envio, estado):
    _con_webpush(monkeypatch, envio, estado)
    r = recordatorios.enviar_push({"suscripcion": _suscripcion()}, "T", "C")
    assert r["ok"] is False and r["estado"] == estado and r["desactivados"] == 2
    assert envio["desactivar"] == ["https://fcm.googleapis.com/fcm/send/abc123"]


@pytest.mark.parametrize("estado", [400, 413, 429, 500])
def test_otros_errores_no_desactivan(monkeypatch, envio, estado):
    _con_webpush(monkeypatch, envio, estado)
    r = recordatorios.enviar_push({"suscripcion": _suscripcion()}, "T", "C")
    assert r["ok"] is False and r["desactivados"] == 0
    assert envio["desactivar"] == []


def test_envio_revalida_endpoint(monkeypatch, envio):
    _con_webpush(monkeypatch, envio, 201)
    with pytest.raises(ErrorValidacion):
        recordatorios.enviar_push({"suscripcion": _suscripcion("https://169.254.169.254/x")}, "T", "C")
    assert envio["webpush"] == []


def test_envio_sin_vapid(monkeypatch, envio):
    monkeypatch.setattr(recordatorios.Config, "VAPID_PRIVATE_KEY", None)
    with pytest.raises(RuntimeError):
        recordatorios.enviar_push({"suscripcion": _suscripcion()}, "T", "C")


# ------------------------------------------------- qué avisos salen hoy

def _rec(id=1, soat=None, tecno=None, activo=True):
    return {"id": id, "activo": activo,
            "fecha_soat": (HOY + timedelta(days=soat)).isoformat() if soat is not None else None,
            "fecha_tecno": (HOY + timedelta(days=tecno)).isoformat() if tecno is not None else None}


def _avisos(recs, ya=frozenset()):
    return recordatorios.avisos_a_enviar(recs, HOY, set(ya))


def test_a_30_dias_dispara_el_30():
    assert _avisos([_rec(soat=30)]) == [(1, "soat", 30, 30)]


def test_a_31_dias_no_dispara():
    assert _avisos([_rec(soat=31)]) == []


def test_catch_up_29_dias_con_30_pendiente_dispara_30():
    assert _avisos([_rec(soat=29)]) == [(1, "soat", 30, 29)]


def test_29_dias_con_30_ya_enviado_no_dispara():
    assert _avisos([_rec(soat=29)], {(1, "soat", 30)}) == []


def test_umbral_ya_enviado_se_saltea():
    assert _avisos([_rec(soat=15)], {(1, "soat", 15)}) == []


@pytest.mark.parametrize("dias, umbral", [(16, 30), (15, 15), (8, 15), (7, 7), (2, 7), (1, 1), (0, 1)])
def test_bucket_es_el_umbral_mas_chico_mayor_o_igual(dias, umbral):
    assert _avisos([_rec(soat=dias)]) == [(1, "soat", umbral, dias)]


def test_soat_y_tecno_disparan_independientes():
    avisos = _avisos([_rec(soat=7, tecno=30)], {(1, "soat", 30), (1, "soat", 15)})
    assert sorted(avisos) == [(1, "soat", 7, 7), (1, "tecno", 30, 30)]


def test_lo_enviado_de_un_tipo_no_afecta_al_otro():
    assert _avisos([_rec(soat=7, tecno=7)], {(1, "soat", 7)}) == [(1, "tecno", 7, 7)]


def test_sin_esa_fecha_no_dispara():
    assert _avisos([_rec(soat=None, tecno=15)]) == [(1, "tecno", 15, 15)]
    assert _avisos([_rec(soat=None, tecno=None)]) == []


def test_ya_vencido_no_dispara():
    assert _avisos([_rec(soat=-1)]) == []


def test_inactivo_no_dispara():
    assert _avisos([_rec(soat=7, activo=False)]) == []


def test_acepta_fechas_como_date():
    r = {"id": 3, "fecha_soat": HOY + timedelta(days=7), "fecha_tecno": None}
    assert _avisos([r]) == [(3, "soat", 7, 7)]


def test_texto_aviso():
    t = recordatorios.texto_aviso("tecno", "2027-03-15", 15)
    assert t["titulo"] == "Tu tecnomecánica vence pronto"
    assert t["cuerpo"] == "Vence en 15 días (15 de marzo de 2027). Renuévalo para evitar multas."
    assert recordatorios.texto_aviso("soat", "2027-03-15", 1)["cuerpo"].startswith("Vence mañana (")
    assert recordatorios.texto_aviso("soat", "2027-03-15", 0)["cuerpo"].startswith("Vence hoy (")

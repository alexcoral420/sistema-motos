"""
Pruebas del servicio de personas (app/servicios/personas.py) y de la
traducción del unique de cédula en el repositorio.

No tocan la base: el repositorio se reemplaza con monkeypatch.
Correr desde la raíz del proyecto:  python -m pytest tests/
"""

import pytest
from postgrest.exceptions import APIError

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import personas


# ------------------------------------------------------------
#  normalizar_cedula
# ------------------------------------------------------------

@pytest.mark.parametrize("entrada, esperado", [
    ("1.234.567-8", "12345678"),
    (" 52 123 456 ", "52123456"),
    ("AB-12345", "AB12345"),
    ("123456789012345", "123456789012345"),   # 15: límite superior
    ("12345", "12345"),                       # 5: límite inferior
])
def test_normalizar_cedula_validas(entrada, esperado):
    assert personas.normalizar_cedula(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", None, "  ", ". - ."])
def test_normalizar_cedula_vacia(entrada):
    with pytest.raises(ErrorValidacion, match="obligatoria"):
        personas.normalizar_cedula(entrada)


@pytest.mark.parametrize("entrada", [
    "1234",               # muy corta
    "1234567890123456",   # muy larga
    "123$456",            # símbolo no permitido
    "123_456",
])
def test_normalizar_cedula_invalida(entrada):
    with pytest.raises(ErrorValidacion, match="no es válida"):
        personas.normalizar_cedula(entrada)


# ------------------------------------------------------------
#  obtener_o_crear
# ------------------------------------------------------------

@pytest.fixture
def repo_falso(monkeypatch):
    """Repositorio en memoria: registra búsquedas y creaciones."""
    estado = {"personas": {}, "buscadas": [], "creadas": [], "siguiente_id": 100}

    def buscar(cedula):
        estado["buscadas"].append(cedula)
        return estado["personas"].get(cedula)

    def crear(datos):
        estado["creadas"].append(datos)
        nueva = dict(datos, id=estado["siguiente_id"])
        estado["siguiente_id"] += 1
        estado["personas"][datos["cedula"]] = nueva
        return nueva

    monkeypatch.setattr(repositorios, "buscar_persona_por_cedula", buscar)
    monkeypatch.setattr(repositorios, "crear_persona", crear)
    return estado


def test_reutiliza_persona_existente_sin_actualizar(repo_falso):
    repo_falso["personas"]["12345678"] = {
        "id": 7, "cedula": "12345678", "telefono": "3001112222", "correo": None}

    persona_id = personas.obtener_o_crear(
        {"cedula": "12.345.678", "telefono": "3999999999", "correo": "nuevo@x.co"})

    assert persona_id == 7
    assert repo_falso["buscadas"] == ["12345678"]   # busca ya normalizada
    assert repo_falso["creadas"] == []               # no crea ni actualiza
    assert repo_falso["personas"]["12345678"]["telefono"] == "3001112222"


def test_crea_persona_nueva_con_datos_limpios(repo_falso):
    persona_id = personas.obtener_o_crear(
        {"cedula": "99.999.999", "nombre": "  Ana Pérez ", "telefono": "  ", "correo": "a@b.co"})

    assert persona_id == 100
    assert repo_falso["creadas"] == [{
        "nombre": "Ana Pérez",
        "cedula": "99999999",
        "telefono": None,      # vacío -> None
        "correo": "a@b.co",
    }]


def test_cedula_invalida_no_toca_el_repositorio(repo_falso):
    with pytest.raises(ErrorValidacion):
        personas.obtener_o_crear({"cedula": "12"})
    assert repo_falso["buscadas"] == []
    assert repo_falso["creadas"] == []


def test_carrera_unique_reutiliza_la_persona_creada_por_otro(monkeypatch):
    """Entre la búsqueda y el insert otro registro creó la cédula."""
    busquedas = []

    def buscar(cedula):
        busquedas.append(cedula)
        return None if len(busquedas) == 1 else {"id": 42, "cedula": cedula}

    def crear(datos):
        raise repositorios.RegistroDuplicado("duplicate key")

    monkeypatch.setattr(repositorios, "buscar_persona_por_cedula", buscar)
    monkeypatch.setattr(repositorios, "crear_persona", crear)

    assert personas.obtener_o_crear({"cedula": "555555"}) == 42
    assert busquedas == ["555555", "555555"]


def test_carrera_sin_persona_tras_duplicado_relanza(monkeypatch):
    """Si tras el duplicado sigue sin aparecer, no se inventa un id."""
    monkeypatch.setattr(repositorios, "buscar_persona_por_cedula", lambda c: None)

    def crear(datos):
        raise repositorios.RegistroDuplicado("duplicate key")

    monkeypatch.setattr(repositorios, "crear_persona", crear)

    with pytest.raises(repositorios.RegistroDuplicado):
        personas.obtener_o_crear({"cedula": "555555"})


# ------------------------------------------------------------
#  repositorios.crear_persona: traducción del error de Postgres
# ------------------------------------------------------------

class _SupabaseQueFalla:
    """Imita la cadena table().insert().execute() lanzando un APIError."""

    def __init__(self, codigo):
        self.codigo = codigo

    def table(self, nombre):
        return self

    def insert(self, datos):
        return self

    def execute(self):
        raise APIError({"code": self.codigo, "message": "error simulado"})


def test_crear_persona_traduce_unique_a_registro_duplicado(monkeypatch):
    monkeypatch.setattr(repositorios, "get_supabase_admin",
                        lambda: _SupabaseQueFalla("23505"))
    with pytest.raises(repositorios.RegistroDuplicado):
        repositorios.crear_persona({"cedula": "123456"})


def test_crear_persona_no_oculta_otros_errores(monkeypatch):
    monkeypatch.setattr(repositorios, "get_supabase_admin",
                        lambda: _SupabaseQueFalla("42501"))   # permiso denegado
    with pytest.raises(APIError):
        repositorios.crear_persona({"cedula": "123456"})

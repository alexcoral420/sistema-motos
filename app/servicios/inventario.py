"""
Servicio de inventario: la lógica de negocio de las motos.

>>> MODO DATOS DE PRUEBA (temporal) <
Mientras trabajamos la seguridad, NO conectamos a Supabase para no tocar
la base de datos de producción. En su lugar, este servicio devuelve una
lista fija de motos "de mentira" definida más abajo (_MOTOS_PRUEBA).

Gracias a la arquitectura por capas, las rutas y los templates NO se
enteran: siguen llamando a las mismas funciones (listar_motos_disponibles,
obtener_moto, etc.). El día que queramos datos reales, descomentamos la
línea que llama al repositorio y borramos los datos de prueba. Un solo
archivo cambia.
"""

# Cuando conectemos la base de datos real, se reactiva esta importación:
# from app.db import repositorios


# ============================================================
#  DATOS DE PRUEBA (temporal, se borra al conectar Supabase)
# ============================================================
# Cada moto es un diccionario con los MISMOS campos que devuelve Supabase,
# para que los templates funcionen igual que con datos reales.

_MOTOS_PRUEBA = [
    {
        "id": 1,
        "marca": "Yamaha",
        "modelo": "MT-03",
        "anio": 2022,
        "color": "Azul",
        "precio": 18500000,
        "kilometraje": 8200,
        "foto_url": "https://placehold.co/600x400/161616/ff7a00?text=Yamaha+MT-03",
        "estado": "disponible",
        "descripcion": "Naked deportiva, único dueño, papeles al día.",
        "soat": "2025-12",
        "tecno": "2025-10",
        "placa": "ABC12D",
    },
    {
        "id": 2,
        "marca": "Honda",
        "modelo": "CB160F",
        "anio": 2021,
        "color": "Rojo",
        "precio": 7200000,
        "kilometraje": 15400,
        "foto_url": "https://placehold.co/600x400/161616/ff7a00?text=Honda+CB160F",
        "estado": "disponible",
        "descripcion": "Ideal para ciudad, bajo consumo, muy económica.",
        "soat": "2026-03",
        "tecno": None,
        "placa": "XYZ98E",
    },
    {
        "id": 3,
        "marca": "Suzuki",
        "modelo": "GN125",
        "anio": 2019,
        "color": "Negro",
        "precio": 4800000,
        "kilometraje": 28900,
        "foto_url": None,  # a propósito sin foto: prueba el caso "sin imagen"
        "estado": "disponible",
        "descripcion": "Clásica confiable, motor a toda prueba.",
        "soat": None,
        "tecno": None,
        "placa": None,
    },
]


# ============================================================
#  FUNCIONES DEL SERVICIO
#  (misma firma que la versión real; solo cambia la fuente de datos)
# ============================================================

def listar_motos_disponibles():
    """Motos con estado 'disponible' (catálogo público y conteo de inicio)."""
    # Versión real (futura):
    # return repositorios.obtener_motos_disponibles()
    return [m for m in _MOTOS_PRUEBA if m["estado"] == "disponible"]


def listar_todas_las_motos():
    """Todas las motos (panel administrativo)."""
    # return repositorios.obtener_todas_las_motos()
    return list(_MOTOS_PRUEBA)


def obtener_moto(id: int):
    """Una moto por su id, o None si no existe."""
    # return repositorios.obtener_moto_por_id(id)
    for moto in _MOTOS_PRUEBA:
        if moto["id"] == id:
            return moto
    return None


def obtener_galeria(moto_id: int):
    """Fotos de galería de una moto. En modo prueba, sin galería (lista vacía)."""
    # return repositorios.obtener_fotos_moto(moto_id)
    return []

    # ============================================================
#  ESCRITURA (modo prueba: simula sin tocar la base de datos)
# ============================================================
# Cuando conectemos Supabase, estas funciones llamarán al repositorio.
# Por ahora solo imprimen lo que HARÍAN, para probar el panel sin
# escribir en producción.

def agregar_moto(datos: dict):
    """Agregaría una moto nueva. En modo prueba, solo lo registra."""
    # return repositorios.agregar_moto(datos)
    print(f"[PRUEBA] Se agregaría la moto: {datos.get('marca')} {datos.get('modelo')}")
    return {"id": 999, **datos}


def actualizar_moto(id: int, datos: dict):
    """Actualizaría una moto existente. En modo prueba, solo lo registra."""
    # return repositorios.actualizar_moto(id, datos)
    print(f"[PRUEBA] Se actualizaría la moto id={id}")
    return {"id": id, **datos}


def marcar_vendida(id: int):
    """Marcaría una moto como vendida. En modo prueba, solo lo registra."""
    # return repositorios.marcar_como_vendida(id)
    print(f"[PRUEBA] Se marcaría como vendida la moto id={id}")
    return True


def eliminar_moto(id: int):
    """Eliminaría una moto. En modo prueba, solo lo registra."""
    # return repositorios.eliminar_moto(id)
    print(f"[PRUEBA] Se eliminaría la moto id={id}")
    return True
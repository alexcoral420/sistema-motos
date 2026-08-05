"""
Servicio de reportes de gerencia.

Lee las vistas SQL de la base (reporte_*). Las vistas hacen el trabajo
pesado (agrupar, contar, cruzar tablas); aquí solo las exponemos como
funciones limpias para que la ruta las use, igual que los demás servicios.

Estas vistas contienen datos sensibles del negocio (ventas, ingresos),
por eso solo las lee la conexión admin (service_role); el rol público
no tiene permiso SELECT sobre ellas.
"""

from app.db import repositorios


def ventas_por_usuario():
    """Cuántas motos ha vendido cada persona."""
    return repositorios.reporte_ventas_por_usuario()


def ventas_por_semana():
    """Ritmo de ventas semana a semana."""
    return repositorios.reporte_ventas_por_semana()


def motos_mas_consultadas():
    """Ranking de motos por número de consultas (interés)."""
    return repositorios.reporte_motos_consultadas()


def consultas_por_marca():
    """Qué marcas generan más interés (guía de compra de inventario)."""
    return repositorios.reporte_consultas_por_marca()

def permutas_por_usuario():
    """Cuántas permutas ha cerrado cada asesor."""
    return repositorios.reporte_permutas_por_usuario()


def modelos_permutados():
    """Qué modelos se mueven más en permutas (entrantes + salientes)."""
    return repositorios.reporte_modelos_permutados()
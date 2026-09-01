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

def ventas_detalle(limite=100):
    """Cada venta individual: asesor, moto, placa y fecha."""
    return repositorios.reporte_ventas_detalle(limite)

def verificar_venta(venta_id, usuario_nombre):
    """Marca una venta como verificada por gerencia."""
    return repositorios.marcar_venta_verificada(venta_id, usuario_nombre)

def compras_detalle(limite=100):
    """Cada compra individual: asesor, moto, placa y fecha."""
    return repositorios.reporte_compras_detalle(limite)

def verificar_compra(compra_id, usuario_nombre):
    """Marca una compra como verificada por gerencia."""
    return repositorios.marcar_compra_verificada(compra_id, usuario_nombre)

def documentos_por_vencer():
    """Motos con SOAT o tecno próximos a vencer."""
    return repositorios.motos_documentos_por_vencer()
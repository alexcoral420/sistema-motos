"""
Configuración del logging de auditoría (vulnerabilidad #9).

Reemplaza los print() temporales por un sistema de registro real:
  - Guarda en archivo (logs/auditoria.log) para consultar el historial.
  - Muestra también en consola (útil en desarrollo).
  - Cada línea lleva fecha, hora y nivel de gravedad automáticamente.

REGLA DE ORO (seguridad del propio log):
Registramos el EVENTO, nunca el SECRETO. Nada de contraseñas, tokens,
ni datos personales completos. El log dice qué pasó y cuándo, sin
convertirse él mismo en una fuga de datos.

Niveles de gravedad (de menor a mayor):
  INFO     -> algo normal ocurrió (login exitoso, acción de admin).
  WARNING  -> algo sospechoso pero no roto (firma inválida, login fallido).
  ERROR    -> algo falló (una excepción controlada).
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def configurar_logging(app):
    """
    Configura el logging de auditoría para la app.

    Se llama una vez desde el factory. Crea la carpeta de logs si no
    existe y conecta dos destinos: el archivo y la consola.
    """
    # Carpeta donde vivirán los archivos de log. La creamos si no existe.
    # exist_ok=True evita error si ya está creada.
    carpeta_logs = "logs"
    os.makedirs(carpeta_logs, exist_ok=True)

    # Formato de cada línea del log. Ejemplo de salida:
    # 2026-07-14 10:30:15 | WARNING | auditoria | Login fallido: usuario 'admin'
    formato = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Destino 1: archivo con rotación ---
    # RotatingFileHandler evita que el archivo crezca sin límite: cuando
    # llega a maxBytes, lo archiva y empieza uno nuevo. Guardamos hasta
    # backupCount archivos viejos. Así el disco nunca se llena de logs.
    archivo = RotatingFileHandler(
        os.path.join(carpeta_logs, "auditoria.log"),
        maxBytes=1_000_000,   # ~1 MB por archivo
        backupCount=5,        # conserva los 5 anteriores
        encoding="utf-8",
    )
    archivo.setFormatter(formato)

    # --- Destino 2: consola ---
    consola = logging.StreamHandler()
    consola.setFormatter(formato)

    # Creamos (u obtenemos) el logger de auditoría con un nombre propio.
    # Usar un nombre nos permite referirnos a él desde cualquier archivo
    # con logging.getLogger("auditoria") y que sea SIEMPRE el mismo.
    logger = logging.getLogger("auditoria")

    # Nivel mínimo que se registra. En desarrollo: INFO (vemos todo).
    # En producción podríamos subirlo a WARNING para menos ruido.
    nivel = logging.INFO if app.config.get("DEBUG") else logging.WARNING
    logger.setLevel(nivel)

    # Evita duplicados si configurar_logging se llamara más de una vez
    # (por ejemplo, en tests que crean varias apps).
    if not logger.handlers:
        logger.addHandler(archivo)
        logger.addHandler(consola)

    # Un primer registro para confirmar que el logging arrancó.
    logger.info("Sistema de logging de auditoría iniciado.")

    return logger


def obtener_logger():
    """
    Devuelve el logger de auditoría para usarlo desde cualquier archivo.

    Uso en otros módulos:
        from app.seguridad.logging_config import obtener_logger
        log = obtener_logger()
        log.warning("Login fallido: usuario '%s'", usuario)
    """
    return logging.getLogger("auditoria")
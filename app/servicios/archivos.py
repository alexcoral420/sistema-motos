"""
Servicio de archivos: subida validada de imágenes (vulnerabilidad #7).

El sistema viejo validaba así:
    extension = nombre_archivo.split('.')[-1]   # <-- confía en el NOMBRE

Problema: el nombre no prueba nada. Cualquiera puede renombrar un
programa malicioso a "foto.jpg" y pasaría la validación.

Aquí validamos con MAGIC BYTES: los primeros bytes de un archivo llevan
una firma binaria característica de su formato, puesta por el programa
que lo creó. No dependen del nombre. Miramos DENTRO del archivo en vez
de creerle a la etiqueta.

    JPEG -> FF D8 FF
    PNG  -> 89 50 4E 47 0D 0A 1A 0A
    WEBP -> "RIFF" .... "WEBP"

Enfoque LISTA BLANCA: solo aceptamos estos tres formatos; todo lo demás
se rechaza, sin importar cómo se llame el archivo.
"""

import uuid

from app.seguridad.validadores import ErrorValidacion

# Tamaño máximo permitido por archivo (5 MB), igual que el límite del
# bucket. Doble capa: la app rechaza antes de subir, el bucket también.
MAX_BYTES = 5 * 1024 * 1024

# Firmas binarias de los formatos permitidos (lista blanca).
# Cada entrada: (bytes de la firma, extensión, content-type)
_FIRMAS = [
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
]


def _detectar_tipo(contenido: bytes):
    """
    Identifica el formato real del archivo por sus magic bytes.

    Devuelve (extension, content_type) si es un formato permitido,
    o None si no reconoce la firma (archivo no permitido).
    """
    # JPEG y PNG: comparación directa del inicio del archivo.
    for firma, extension, content_type in _FIRMAS:
        if contenido.startswith(firma):
            return extension, content_type

    # WEBP es especial: empieza con "RIFF", 4 bytes de tamaño, y luego
    # "WEBP". Por eso se comprueba en dos posiciones.
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp", "image/webp"

    # Ninguna firma conocida -> no es una imagen permitida.
    return None


def validar_imagen(archivo) -> dict:
    """
    Valida un archivo subido y devuelve su contenido y tipo real.

    archivo: el objeto de Flask (request.files[...]).

    Devuelve un dict: {"contenido": bytes, "extension": str, "content_type": str}
    Lanza ErrorValidacion si el archivo no es una imagen válida o es
    demasiado grande.
    """
    if archivo is None or not archivo.filename:
        raise ErrorValidacion("No se recibió ningún archivo.", "foto")

    # Leemos el contenido completo en memoria para poder inspeccionarlo.
    contenido = archivo.read()
    # Rebobinamos por si alguien más necesita leerlo después.
    archivo.seek(0)

    if not contenido:
        raise ErrorValidacion("El archivo está vacío.", "foto")

    # --- Control de tamaño (antes de nada más) ---
    if len(contenido) > MAX_BYTES:
        raise ErrorValidacion(
            "La imagen supera el tamaño máximo permitido (5 MB).", "foto")

    # --- Validación por MAGIC BYTES (el control de verdad) ---
    tipo = _detectar_tipo(contenido)
    if tipo is None:
        # No importa que se llame "foto.jpg": su contenido no es una
        # imagen JPEG/PNG/WEBP. Se rechaza.
        raise ErrorValidacion(
            "El archivo no es una imagen válida (solo JPG, PNG o WEBP).", "foto")

    extension, content_type = tipo
    return {
        "contenido": contenido,
        "extension": extension,
        "content_type": content_type,
    }


def generar_nombre_seguro(extension: str, carpeta: str = "") -> str:
    """
    Genera un nombre de archivo aleatorio y seguro para el bucket.

    Por qué NO usar el nombre original del archivo:
      - Podría contener caracteres peligrosos o rutas ("../../secreto").
      - Podría chocar con otro archivo del mismo nombre.
      - Podría revelar información (nombres de clientes, rutas internas).

    Usamos un UUID: un identificador único aleatorio. La extensión la
    ponemos según el tipo REAL detectado, no según el nombre original.
    """
    nombre = f"{uuid.uuid4()}.{extension}"
    if carpeta:
        return f"{carpeta}/{nombre}"
    return nombre
"""
Servicio de archivos: subida validada y optimizada de imágenes.

Dos trabajos:

1. VALIDAR (vulnerabilidad #7). Con magic bytes: los primeros bytes de un
   archivo llevan la firma binaria de su formato real. El nombre no prueba
   nada; el contenido sí.

2. COMPRIMIR. Una foto de celular pesa 3-8 MB. Guardarla tal cual hace que
   el catálogo tarde una eternidad en datos móviles. La redimensionamos y
   la convertimos a WebP: de ~4 MB a ~200 KB, sin diferencia visible.
"""

import io
import uuid

from PIL import Image, ImageOps

from app.seguridad.validadores import ErrorValidacion

MAX_BYTES = 5 * 1024 * 1024

# Defensa contra BOMBAS DE DESCOMPRESIÓN: un PNG de 10 KB puede declarar
# 50.000 x 50.000 píxeles y, al abrirlo, agotar toda la RAM del servidor.
# Pasa los magic bytes (es un PNG legítimo) y pesa poco: nuestras otras
# validaciones no lo detectan. Este límite sí.
Image.MAX_IMAGE_PIXELS = 50_000_000

ANCHO_MAX = 1600      # suficiente: la galería se ve a 440px
CALIDAD_WEBP = 82     # buen equilibrio calidad/peso

_FIRMAS = [
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
]


def _detectar_tipo(contenido: bytes):
    """Identifica el formato real por sus magic bytes, o None."""
    for firma, extension, content_type in _FIRMAS:
        if contenido.startswith(firma):
            return extension, content_type

    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp", "image/webp"

    return None


def _comprimir(contenido: bytes) -> bytes:
    """
    Redimensiona y convierte a WebP.

    Efectos secundarios importantes y deseados:
      - Se aplica la orientación EXIF antes de descartarla, para que las
        fotos de celular no salgan giradas.
      - Los metadatos EXIF NO se copian al WebP. Eso BORRA las coordenadas
        GPS que los celulares incrustan en cada foto. Publicar fotos con
        GPS revela ubicaciones sin que nadie se dé cuenta.
    """
    imagen = Image.open(io.BytesIO(contenido))

    # El celular no rota el píxel: guarda una etiqueta EXIF que dice "esta
    # foto va girada 90°". Si descartamos el EXIF sin aplicarlo, la foto
    # sale de lado. Esto la rota de verdad y ya no hace falta la etiqueta.
    imagen = ImageOps.exif_transpose(imagen)

    # Modos raros (paleta, CMYK) a RGB. WebP maneja RGB y RGBA sin problema.
    if imagen.mode not in ("RGB", "RGBA"):
        imagen = imagen.convert("RGB")

    # Redimensionar solo si es más ancha que el máximo (nunca agrandamos).
    if imagen.width > ANCHO_MAX:
        alto = round(imagen.height * ANCHO_MAX / imagen.width)
        imagen = imagen.resize((ANCHO_MAX, alto), Image.LANCZOS)

    salida = io.BytesIO()
    imagen.save(salida, format="WEBP", quality=CALIDAD_WEBP, method=6)
    return salida.getvalue()


def validar_imagen(archivo) -> dict:
    """
    Valida un archivo subido, lo comprime, y devuelve el resultado listo
    para guardar. Lanza ErrorValidacion si no es una imagen aceptable.
    """
    if archivo is None or not archivo.filename:
        raise ErrorValidacion("No se recibió ningún archivo.", "foto")

    contenido = archivo.read()
    archivo.seek(0)

    if not contenido:
        raise ErrorValidacion("El archivo está vacío.", "foto")

    if len(contenido) > MAX_BYTES:
        raise ErrorValidacion(
            "La imagen supera el tamaño máximo permitido (5 MB).", "foto")

    # Capa 1: magic bytes. ¿Es realmente una imagen permitida?
    if _detectar_tipo(contenido) is None:
        raise ErrorValidacion(
            "El archivo no es una imagen válida (solo JPG, PNG o WEBP).", "foto")

    # Capa 2: que Pillow pueda abrirla y procesarla de verdad. Un archivo
    # con magic bytes correctos pero contenido corrupto falla aquí.
    try:
        comprimido = _comprimir(contenido)
    except Image.DecompressionBombError:
        raise ErrorValidacion(
            "La imagen tiene dimensiones desproporcionadas.", "foto")
    except Exception:
        raise ErrorValidacion(
            "No se pudo procesar la imagen (¿archivo dañado?).", "foto")

    # Todo lo que entra sale como WebP, sin importar cómo entró.
    return {
        "contenido": comprimido,
        "extension": "webp",
        "content_type": "image/webp",
    }


def generar_nombre_seguro(extension: str, carpeta: str = "") -> str:
    """
    Nombre aleatorio (UUID) para el bucket. El nombre original se descarta:
    podría traer rutas maliciosas, chocar con otro, o filtrar información.
    """
    nombre = f"{uuid.uuid4()}.{extension}"
    if carpeta:
        return f"{carpeta}/{nombre}"
    return nombre
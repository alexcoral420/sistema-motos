"""
Genera los íconos de la PWA (static/pwa/) a partir del logo.

Uso:
    python scripts/generar_iconos_pwa.py                 # usa static/logo.png
    python scripts/generar_iconos_pwa.py ruta/logo.png   # otro logo

Se corre a mano, una vez por cambio de logo; los PNG resultantes se
versionan en el repo. Requiere Pillow (no está en requirements.txt porque
la app no lo usa en tiempo de ejecución).

Cada ícono es el logo centrado sobre un cuadrado opaco del color de
fondo del sitio:
  - Opaco porque iOS rellena la transparencia del apple-touch-icon con
    negro o blanco según la versión, y Android hace lo mismo con los
    íconos "maskable".
  - Con margen porque Android recorta los íconos maskable a un círculo
    o "squircle": solo el 80% central (la "safe zone") está garantizado
    visible. El logo ocupa el 70% del lado para quedar holgado adentro.

Lo ideal es un logo de 512 px o más: si es más chico, el ícono de 512
sale agrandado (borroso). El script avisa cuando pasa.
"""

import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "static" / "pwa"

# --negro-900 de las plantillas públicas: mismo color que el
# background_color del manifest, para que el ícono y la pantalla de
# carga se vean continuos.
FONDO = (5, 5, 5, 255)

# Fracción del lado que ocupa el logo (dentro de la safe zone del 80%).
PROPORCION_LOGO = 0.70

ICONOS = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
}


def color_fondo(logo: Image.Image) -> tuple:
    """
    Si el logo trae fondo propio opaco (el actual es un cuadrado negro
    #000), rellenar con ese mismo color: con FONDO se notaría el borde
    del cuadrado. Si el logo es transparente, se usa FONDO.
    """
    esquina = logo.getpixel((0, 0))
    return esquina if esquina[3] == 255 else FONDO


def generar(logo: Image.Image, lado: int) -> Image.Image:
    lienzo = Image.new("RGBA", (lado, lado), color_fondo(logo))
    maximo = round(lado * PROPORCION_LOGO)
    escala = maximo / max(logo.size)
    tamano = (round(logo.width * escala), round(logo.height * escala))
    reducido = logo.resize(tamano, Image.LANCZOS)
    posicion = ((lado - tamano[0]) // 2, (lado - tamano[1]) // 2)
    lienzo.alpha_composite(reducido, posicion)
    return lienzo.convert("RGB")


def main():
    origen = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "static" / "logo.png"
    logo = Image.open(origen).convert("RGBA")
    DESTINO.mkdir(parents=True, exist_ok=True)

    for nombre, lado in ICONOS.items():
        generar(logo, lado).save(DESTINO / nombre, optimize=True)
        necesario = round(lado * PROPORCION_LOGO)
        aviso = ""
        if max(logo.size) < necesario:
            aviso = f"  (AVISO: logo de {max(logo.size)} px agrandado a {necesario} px, sale borroso)"
        print(f"{nombre}: {lado}x{lado}{aviso}")


if __name__ == "__main__":
    main()

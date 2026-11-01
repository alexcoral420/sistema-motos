"""
Envía UN push de prueba a un recordatorio (Fase 2: envío manual).

Uso:
    python scripts/enviar_push_prueba.py          # el activo más reciente
    python scripts/enviar_push_prueba.py 42       # el recordatorio id=42

Lee VAPID_PRIVATE_KEY y VAPID_SUBJECT del entorno (.env). Si el servicio
de push responde 404/410, la suscripción murió y los recordatorios con
ese endpoint quedan con activo=false.

No programa nada: el envío diario automático es la Fase 3.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests.exceptions import RequestException

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import recordatorios

TITULO = "Universal Motors"
CUERPO = "Push de prueba: si ves esto, los recordatorios funcionan."
URL = "/recordatorio-soat"


def main():
    if len(sys.argv) > 2:
        sys.exit("Uso: python scripts/enviar_push_prueba.py [id_recordatorio]")

    if len(sys.argv) == 2:
        try:
            recordatorio_id = int(sys.argv[1])
        except ValueError:
            sys.exit(f"El id debe ser un número: {sys.argv[1]!r}")
        recordatorio = repositorios.obtener_recordatorio(recordatorio_id)
        if not recordatorio:
            sys.exit(f"No existe el recordatorio id={recordatorio_id}.")
        if not recordatorio.get("activo"):
            print(f"Aviso: el recordatorio id={recordatorio_id} está inactivo; se envía igual.")
    else:
        recordatorio = repositorios.obtener_recordatorio_activo_mas_reciente()
        if not recordatorio:
            sys.exit("No hay recordatorios activos.")

    endpoint = (recordatorio.get("suscripcion") or {}).get("endpoint", "")
    print(f"Recordatorio id={recordatorio['id']} (creado {recordatorio.get('creado_en')})")
    print(f"Endpoint: {endpoint[:60]}...")

    try:
        resultado = recordatorios.enviar_push(recordatorio, TITULO, CUERPO, URL)
    except ErrorValidacion:
        sys.exit("La suscripción guardada no es válida (endpoint o claves); no se envía.")
    except RuntimeError as e:
        sys.exit(str(e))
    except RequestException as e:
        sys.exit(f"Error de red al contactar el servicio de push: {e}")

    if resultado["ok"]:
        print(f"OK: enviado (HTTP {resultado['estado']}).")
    else:
        print(f"FALLÓ: HTTP {resultado['estado']}. {resultado['detalle']}")
        if resultado["desactivados"]:
            print(f"Suscripción muerta: {resultado['desactivados']} recordatorio(s) marcados activo=false.")
        sys.exit(1)


if __name__ == "__main__":
    main()

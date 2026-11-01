"""
Job de envío de recordatorios de vencimiento (Fase 3).

Uso:
    python scripts/enviar_recordatorios.py                  # envía de verdad
    python scripts/enviar_recordatorios.py --dry-run        # solo muestra qué saldría
    python scripts/enviar_recordatorios.py --hoy 2027-02-13 --dry-run

Lee los recordatorios activos que vencen dentro del umbral más grande, los
avisos ya enviados, decide con avisos_a_enviar() qué sale hoy y manda cada
push con enviar_push() (Fase 2). Cada envío exitoso queda en
recordatorios_avisos; un 404/410 desactiva la suscripción.

Pensado para correr una vez al día. Correrlo de más es seguro: lo ya
enviado no se repite.
"""

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests.exceptions import RequestException

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import recordatorios as servicio


def _argumentos():
    p = argparse.ArgumentParser(description="Envía los avisos de vencimiento de SOAT y tecnomecánica.")
    p.add_argument("--dry-run", action="store_true",
                   help="muestra qué se enviaría, sin enviar ni escribir en la base")
    p.add_argument("--hoy", type=date.fromisoformat, metavar="AAAA-MM-DD",
                   help="simula otra fecha como 'hoy' (por defecto, hoy en Colombia)")
    return p.parse_args()


def main():
    args = _argumentos()
    hoy = args.hoy or servicio._hoy()
    hasta = hoy + timedelta(days=max(servicio.UMBRALES_AVISO))
    print(f"Hoy: {hoy}{'  (DRY RUN: no se envía nada)' if args.dry_run else ''}")

    candidatos = repositorios.listar_recordatorios_por_vencer(hoy.isoformat(), hasta.isoformat())
    enviados_antes = repositorios.listar_avisos_enviados([r["id"] for r in candidatos])
    ya_enviados = {(a["recordatorio_id"], a["tipo"], a["umbral"]) for a in enviados_antes}
    avisos = servicio.avisos_a_enviar(candidatos, hoy, ya_enviados)
    por_id = {r["id"]: r for r in candidatos}

    resumen = {"enviados": 0, "muertos": 0, "errores": 0, "duplicados": 0}
    endpoints_muertos = set()

    for recordatorio_id, tipo, umbral, dias in avisos:
        r = por_id[recordatorio_id]
        columna = servicio.TIPOS_AVISO[tipo][0]
        texto = servicio.texto_aviso(tipo, r[columna], dias)
        etiqueta = f"id={recordatorio_id} {tipo} umbral={umbral} dias={dias}"

        if args.dry_run:
            print(f"  [dry-run] {etiqueta}: {texto['cuerpo']}")
            continue

        endpoint = (r.get("suscripcion") or {}).get("endpoint")
        if endpoint in endpoints_muertos:
            print(f"  SALTADO {etiqueta}: la suscripción murió en esta corrida")
            continue

        try:
            resultado = servicio.enviar_push(r, texto["titulo"], texto["cuerpo"], servicio.URL_AVISO)
        except ErrorValidacion:
            resumen["errores"] += 1
            print(f"  ERROR   {etiqueta}: suscripción guardada inválida")
            continue
        except RequestException as e:
            resumen["errores"] += 1
            print(f"  ERROR   {etiqueta}: red: {e}")
            continue

        if resultado["ok"]:
            resumen["enviados"] += 1
            try:
                repositorios.registrar_aviso(recordatorio_id, tipo, umbral)
            except repositorios.RegistroDuplicado:
                resumen["duplicados"] += 1
            print(f"  OK      {etiqueta} (HTTP {resultado['estado']})")
        elif resultado["estado"] in servicio.ESTADOS_SUSCRIPCION_MUERTA:
            resumen["muertos"] += 1
            endpoints_muertos.add(endpoint)
            print(f"  MUERTA  {etiqueta} (HTTP {resultado['estado']}): "
                  f"{resultado['desactivados']} recordatorio(s) desactivados")
        else:
            resumen["errores"] += 1
            print(f"  ERROR   {etiqueta} (HTTP {resultado['estado']}): {resultado['detalle']}")

    print(f"\nEvaluados: {len(candidatos)} recordatorios | avisos que califican: {len(avisos)}")
    if not args.dry_run:
        print(f"Enviados: {resumen['enviados']} | suscripciones muertas: {resumen['muertos']} | "
              f"errores: {resumen['errores']}"
              + (f" | ya registrados por otra corrida: {resumen['duplicados']}" if resumen["duplicados"] else ""))
    if resumen["errores"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

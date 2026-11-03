"""
Job de envío de las alertas del motero ("Mi espacio", Fase B).

Uso:
    python scripts/enviar_alertas.py                  # envía de verdad
    python scripts/enviar_alertas.py --dry-run        # solo muestra qué saldría
    python scripts/enviar_alertas.py --hoy 2027-02-13 --dry-run

Lee las alertas activas por fecha y los avisos ya enviados, decide con
alertas_motero.avisos_a_enviar() qué sale hoy y manda cada aviso a todos
los dispositivos activos del motero dueño (push.enviar_a_suscripcion).

  - Con al menos un dispositivo que lo recibió, el aviso queda en
    alertas_avisos (alerta_id, ciclo, umbral) y no se repite.
  - Un 404/410 desactiva ese dispositivo (dispositivos.activo = false).
  - Si todo falla por algo pasajero (429, 5xx, red), o el motero no tiene
    dispositivos activos, no se registra: la próxima corrida lo reintenta,
    y el bucket manda el aviso vigente cuando active las notificaciones.

No escribe en `alertas`: fecha_objetivo es el ancla y cada ciclo se
calcula con proxima_ocurrencia(). Independiente de enviar_recordatorios.py
(los recordatorios anónimos tienen su propio job).

Pensado para correr una vez al día. Correrlo de más es seguro: lo ya
enviado no se repite.
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from requests.exceptions import RequestException

from app.db import repositorios
from app.seguridad.validadores import ErrorValidacion
from app.servicios import alertas_motero as servicio
from app.servicios import push


def _argumentos():
    p = argparse.ArgumentParser(description="Envía los avisos de las alertas del motero (Mi espacio).")
    p.add_argument("--dry-run", action="store_true",
                   help="muestra qué se enviaría, sin enviar ni escribir en la base")
    p.add_argument("--hoy", type=date.fromisoformat, metavar="AAAA-MM-DD",
                   help="simula otra fecha como 'hoy' (por defecto, hoy en Colombia)")
    return p.parse_args()


def main():
    args = _argumentos()
    hoy = args.hoy or servicio._hoy()
    print(f"Hoy: {hoy}{'  (DRY RUN: no se envía nada)' if args.dry_run else ''}")

    alertas = repositorios.listar_alertas_fecha_activas()
    enviados_antes = repositorios.listar_avisos_alertas([a["id"] for a in alertas]) if alertas else []
    ya_enviados = {(a["alerta_id"], a["ciclo"], a["umbral"]) for a in enviados_antes}
    avisos = servicio.avisos_a_enviar(alertas, hoy, ya_enviados)
    por_id = {a["id"]: a for a in alertas}

    duenos = sorted({por_id[aviso[0]]["usuario_id"] for aviso in avisos})
    dispositivos = repositorios.listar_dispositivos_activos(duenos) if duenos else []
    por_dueno = {}
    for d in dispositivos:
        por_dueno.setdefault(d["usuario_id"], []).append(d)

    resumen = {"enviados": 0, "sin_dispositivo": 0, "muertos": 0, "errores": 0, "duplicados": 0}
    endpoints_muertos = set()

    for alerta_id, ciclo, umbral, dias, ocurrencia in avisos:
        alerta = por_id[alerta_id]
        texto = servicio.texto_aviso_alerta(alerta["tipo"], ocurrencia, dias)
        etiqueta = f"alerta={alerta_id} {alerta['tipo']} ciclo={ciclo} umbral={umbral} dias={dias}"
        destinos = [d for d in por_dueno.get(alerta["usuario_id"], [])
                    if d.get("endpoint") not in endpoints_muertos]

        if args.dry_run:
            print(f"  [dry-run] {etiqueta} -> {len(destinos)} dispositivo(s): {texto['cuerpo']}")
            continue

        if not destinos:
            resumen["sin_dispositivo"] += 1
            print(f"  SIN DISP {etiqueta}: el motero no tiene dispositivos activos")
            continue

        entregado = False
        for d in destinos:
            disp = f"disp={d['id']}"
            try:
                resultado = push.enviar_a_suscripcion(
                    d.get("suscripcion"), texto["titulo"], texto["cuerpo"], servicio.URL_AVISO_ALERTA)
            except ErrorValidacion:
                resumen["errores"] += 1
                print(f"  ERROR    {etiqueta} {disp}: suscripción guardada inválida")
                continue
            except RequestException as e:
                resumen["errores"] += 1
                print(f"  ERROR    {etiqueta} {disp}: red: {e}")
                continue

            if resultado["ok"]:
                entregado = True
                print(f"  OK       {etiqueta} {disp} (HTTP {resultado['estado']})")
            elif push.suscripcion_muerta(resultado["estado"]):
                resumen["muertos"] += 1
                endpoints_muertos.add(resultado["endpoint"])
                n = repositorios.desactivar_dispositivos_por_endpoint(resultado["endpoint"])
                print(f"  MUERTO   {etiqueta} {disp} (HTTP {resultado['estado']}): "
                      f"{n} dispositivo(s) desactivados")
            else:
                resumen["errores"] += 1
                print(f"  ERROR    {etiqueta} {disp} (HTTP {resultado['estado']}): {resultado['detalle']}")

        if entregado:
            resumen["enviados"] += 1
            try:
                repositorios.registrar_aviso_alerta(alerta_id, ciclo, umbral)
            except repositorios.RegistroDuplicado:
                resumen["duplicados"] += 1

    print(f"\nEvaluadas: {len(alertas)} alertas | avisos que califican: {len(avisos)}")
    if not args.dry_run:
        print(f"Enviados: {resumen['enviados']} | sin dispositivo: {resumen['sin_dispositivo']} | "
              f"dispositivos muertos: {resumen['muertos']} | errores: {resumen['errores']}"
              + (f" | ya registrados por otra corrida: {resumen['duplicados']}" if resumen["duplicados"] else ""))
    if resumen["errores"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

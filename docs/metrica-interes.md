# Métrica de interés por rango de precio

Documentación del indicador de demanda del panel de gerencia:
**tasa de interés normalizada por rango de precio, mes a mes.**

- Servicio: `app/servicios/reportes.py` → `interes_por_rango_precio(desde, hasta)`
- Ruta JSON: `GET /admin/gerencia/interes-precio/datos` (roles `admin`, `gerencia`)
- Vista: `app/templates/gerencia/interes_precio.html` (gráfico de líneas, fetch)

---

## 1. Qué pregunta responde

> ¿Qué rango de precio genera más **interés real por moto**, y cómo evoluciona mes a mes?

Donde "interés real" = deseo de la gente, **no** un artefacto de cuántas motos
hay en el rango ni de hace cuánto están publicadas.

El interés se mide por los **clics en "Preguntar por esta moto"** (que redirigen a
WhatsApp). Cada clic es una fila en la tabla `intenciones`. Se cuentan **clics**,
no personas únicas: un clic en 2 motos distintas son 2 intenciones reales (la
persona compara opciones), y ~90 % de las personas hacen un solo clic de todos modos.

---

## 2. Los dos factores que distorsionan los clics crudos

Un conteo crudo de clics mezcla el deseo con dos factores ajenos:

1. **Cantidad de inventario** — un rango con 50 motos junta más clics que uno con 3,
   solo por tener más.
2. **Tiempo de exposición** — una moto publicada hace 90 días tuvo 90 días para
   juntar clics; una de 3 días, apenas 3.

La métrica elimina ambos.

---

## 3. La métrica

```
tasa = (clics ÷ moto-días) × 30      →   clics por moto cada 30 días
```

La clave es el denominador **moto-días**: un moto-día = una moto publicada durante
un día. Al sumar los moto-días de un rango, el denominador crece tanto con la
**cantidad** de motos como con el **tiempo** que estuvieron publicadas. Dividir por
él cancela los dos factores de una sola vez, y deja solo la intensidad del deseo.

El `× 30` es cosmético: convierte una tasa diaria (decimal chico) en "por mes",
más legible.

---

## 4. Fuentes de datos

| Tabla         | Campos usados                        | Para qué                          |
|---------------|--------------------------------------|-----------------------------------|
| `intenciones` | `created_at`, `moto_id`              | Clics (cuándo y a qué moto)       |
| `motos`       | `precio`, `publicada_en`, `estado`   | Rango e inicio de exposición      |
| `ventas`      | `created_at` (por `moto_id`)         | Fin de exposición de las vendidas |

---

## 5. Qué motos entran y cuáles no

- **Entran:** `disponible` y `vendido` **con** registro en `ventas`.
- **Quedan fuera:**
  - `reservado` — no se muestra en el catálogo (no acumula clics); estado deprecado.
  - `por_publicar` — todavía no está expuesta.
  - `vendido` **sin** registro en `ventas` — no se sabe cuándo dejó de exponerse
    (son ventas viejas de la etapa de implementación).

---

## 6. Ventana de exposición de cada moto

```
inicio = publicada_en
fin    = hoy             (si está disponible)
       = fecha de venta  (si está vendida)
```

`publicada_en` se setea automáticamente al publicar (`publicar_moto`). Las motos
publicadas antes de que existiera ese campo se rellenaron con `created_at` como
aproximación (exacto de julio en adelante).

---

## 7. El cálculo, paso a paso

Para **cada mes × cada rango de precio**:

1. **Clasificar** cada moto en su rango según `precio`:
   `Hasta $6M` · `$6–8M` · `$8–12M` · `Más de $12M`
   (los mismos rangos del filtro del catálogo público).
2. **Clics** = contar las intenciones de motos de ese rango cuyo `created_at` cae
   en el mes.
3. **Moto-días** = por cada moto del rango, los días de **solapamiento** entre su
   ventana `[publicada_en, fin]` y el mes `[inicio_mes, fin_mes]`; se suman.
   (Una moto publicada el 20 de octubre aporta 11 días a octubre, no 31.)
4. **Tasa** = `clics ÷ moto-días × 30`.

Todo agrupado por mes en zona horaria **America/Bogota**.

El JSON de salida trae, por serie (rango): `tasas`, y también `clics` y `moto_dias`
crudos, para mostrarlos en el tooltip del gráfico.

---

## 8. Ejemplo real (septiembre 2026, "Hasta $6M")

```
512 clics ÷ 780.7 moto-días = 0.656 clics por moto-día
0.656 × 30 = 19.67 clics por moto al mes
```

Los 780.7 moto-días ≈ 26 motos expuestas durante todo el mes. El 19.67 es la tasa
limpia, comparable con cualquier otro rango o mes.

---

## 9. Por qué el mes en curso (parcial) no distorsiona

El mes actual va solo hasta hoy. Pero como **clics y moto-días se miden sobre el
mismo período parcial**, la tasa (× 30) proyecta igual a un ritmo de 30 días. Una
*tasa* es inmune a los meses incompletos — por eso se eligió esta métrica y no un
volumen.

---

## 10. Supuestos y limitaciones

- `publicada_en` de motos viejas = `created_at` (aproximación; cuenta de más el
  tiempo que una moto estuvo en `por_publicar` antes de publicarse).
- 19 ventas sin registro en `ventas` quedan excluidas (datos legacy).
- Los meses más antiguos son menos confiables que los recientes.
- El gráfico arranca en julio 2026 porque antes no había datos.
- Despublicar/republicar una moto no corta la exposición (se cuenta de corrido);
  es un caso raro y se simplifica.
- `publicada_en` se guarda en UTC; el agrupado por mes convierte a America/Bogota.

---

## 11. Mejoras futuras posibles

- Guardar el **precio en la intención** al momento del clic, para no depender del
  precio actual de la moto (hoy un cambio de precio reclasifica clics históricos).
- Cambiar `motos.moto_id` en `intenciones` de `on delete cascade` a `set null`
  para conservar el histórico de motos borradas (hoy se pierde al borrar).
- Registrar `publicada_en` también en despublicaciones, para manejar huecos de
  exposición con precisión.
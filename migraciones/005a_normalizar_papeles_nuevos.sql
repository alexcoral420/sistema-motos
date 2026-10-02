-- ============================================================
-- 005 — Normalizar papeles marcados como "nuevo"
-- Fecha: 2026-08-27
--
-- La columna soat/tecno es texto libre y algunas motos tenian
-- "nuevo"/"nueva" en vez de fecha, significando que entraron con
-- papeles vencidos (se renuevan al vender). Se les asigna una fecha
-- pasada (2026-06-01) para que el reporte las trate como vencidas.
--
-- PENDIENTE: la causa de fondo es que la columna acepta texto libre.
-- Convertirla a tipo date evitaria estos valores invalidos.
-- ============================================================

-- 2. La vista que lista motos disponibles con sus vencimientos y los días
--    restantes. Conocer qué motos vencen pronto es una palanca de
--    negociación: se puede ofrecer descuento o negociar mejor la venta.
--
-- La conversión a fecha usa una comprobación con regex: si el valor no tiene
-- forma YYYY-MM-DD, se deja en null en vez de romper la vista. Es una red por
-- si vuelve a aparecer texto libre invàlido.
--
-- PENDIENTE: la causa de fondo es que la columna acepta texto. Convertirla a
-- tipo date evitaría estos valores invàlidos (migración futura).
-- ============================================================================

update motos set soat = '2026-06-01' where lower(soat) in ('nueva','nuevo');
update motos set tecno = '2026-06-01' where lower(tecno) in ('nueva','nuevo');


-- 2. La vista.
create or replace view documentos_por_vencer as
    select
        id, marca, modelo, placa, precio, estado,
        case when soat ~ '^\d{4}-\d{2}-\d{2}$' then soat::date end as vence_soat,
        case when soat ~ '^\d{4}-\d{2}-\d{2}$' then soat::date - current_date end as dias_soat,
        case when tecno ~ '^\d{4}-\d{2}-\d{2}$' then tecno::date end as vence_tecno,
        case when tecno ~ '^\d{4}-\d{2}-\d{2}$' then tecno::date - current_date end as dias_tecno
    from motos
    where estado = 'disponible'
    order by least(
        case when soat ~ '^\d{4}-\d{2}-\d{2}$' then soat::date else '9999-12-31'::date end,
        case when tecno ~ '^\d{4}-\d{2}-\d{2}$' then tecno::date else '9999-12-31'::date end
    );

grant select on documentos_por_vencer to service_role;
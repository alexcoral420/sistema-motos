-- ============================================================================
-- 002 — Vista del catálogo ordenada por popularidad reciente
-- Fecha: 2026-08-25
--
-- El catálogo mostraba las motos por fecha de ingreso. Con más de 130 unidades
-- y 15 por página, las que de verdad interesan quedaban enterradas.
--
-- Esta vista devuelve las motos disponibles con dos columnas calculadas:
-- cuántas consultas recibieron en los últimos 15 días, y los datos de su sede.
-- La ventana móvil de 15 días evita que una moto vieja con consultas antiguas
-- le gane indefinidamente a una nueva que está funcionando.
--
-- Se resuelve en la base y no en la aplicación porque el orden debe aplicarse
-- ANTES de paginar: si ordenáramos en Python, habría que traer las 130 motos
-- para mostrar 15, que es justo lo que queremos evitar.
--
-- El LEFT JOIN con intenciones es deliberado: sin él, una moto sin consultas
-- desaparecería del catálogo.
-- ============================================================================

create or replace view catalogo_ordenado as
    select
        m.*,
        s.nombre as sede_nombre,
        s.direccion as sede_direccion,
        coalesce(count(i.id) filter (
            where i.created_at > now() - interval '15 days'
        ), 0) as consultas_recientes
    from motos m
    left join sedes s on s.id = m.sede_id
    left join intenciones i on i.moto_id = m.id
    where m.estado = 'disponible'
    group by m.id, s.nombre, s.direccion;

grant select on catalogo_ordenado to service_role;
grant select on catalogo_ordenado to anon;
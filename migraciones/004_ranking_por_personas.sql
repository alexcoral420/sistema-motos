-- ============================================================================
-- 004 — El ranking cuenta personas, no clics
-- Fecha: 2026-08-25
--
-- Hasta ahora el ranking contaba intenciones: alguien que tocaba la misma
-- moto cinco veces pesaba igual que cinco personas distintas. Con la columna
-- sesion_id (migración 003) podemos contar visitantes únicos.
--
-- ADVERTENCIA: las intenciones anteriores a la migración 003 no tienen
-- sesion_id, así que el count(distinct) las ignora. El ranking se reinicia
-- y se reconstruye con datos nuevos a medida que llegan.
-- ============================================================================

create or replace view catalogo_ordenado as
    select
        m.*,
        s.nombre as sede_nombre,
        s.direccion as sede_direccion,
        count(distinct i.sesion_id) filter (
            where i.created_at > now() - interval '15 days'
        ) as consultas_recientes
    from motos m
    left join sedes s on s.id = m.sede_id
    left join intenciones i on i.moto_id = m.id
    where m.estado = 'disponible'
    group by m.id, s.nombre, s.direccion;

grant select on catalogo_ordenado to service_role, anon;
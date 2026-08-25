-- ============================================================================
-- 003 — Identificador de sesión en las intenciones
-- Fecha: 2026-08-25
--
-- La tabla registraba clics, no personas. Alguien que compara cinco motos
-- generaba cinco intenciones, con el mismo peso que cinco personas distintas.
-- Eso distorsiona el ranking que ahora ordena el catálogo.
--
-- 'sesion_id' es un identificador ANÓNIMO generado por el servidor y guardado
-- en la cookie de sesión. No identifica a la persona: es un número al azar que
-- solo sirve para agrupar los clics de una misma visita.
-- ============================================================================

alter table intenciones
    add column if not exists sesion_id text;

create index if not exists idx_intenciones_sesion
    on intenciones (sesion_id);
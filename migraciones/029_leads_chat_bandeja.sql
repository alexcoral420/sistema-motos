-- 029_leads_chat_bandeja.sql
--
-- Bandeja de leads del chat para los asesores (/admin/leads).
--
-- Cada lead guardado por el chat se le avisa por push a los asesores; el
-- primero que lo toma se lo queda. Estas columnas llevan ese ciclo:
--
--   estado         nuevo -> tomado -> contactado | descartado
--   asesor_id      quien lo tomo (FK usuarios)
--   asesor_nombre  su nombre congelado como texto, igual que en ventas,
--                  compras y permutas: el historial sigue legible si el
--                  usuario cambia de nombre o se desactiva
--   tomado_en      cuando lo tomo
--   gestionado_en  cuando lo marco contactado o descartado
--
-- "Tomar" es un UPDATE condicionado (estado = 'nuevo' y asesor_id nulo):
-- si dos asesores tocan a la vez, solo a uno le devuelve la fila.
--
-- Los leads que ya existian quedan en 'nuevo' y aparecen en la bandeja.
--
-- ORDEN DE DESPLIEGUE: aplicar ANTES de desplegar el codigo (despues de
-- la 027 y la 028).

alter table leads_chat add column if not exists estado        text not null default 'nuevo';
alter table leads_chat add column if not exists asesor_id     bigint references usuarios(id) on delete set null;
alter table leads_chat add column if not exists asesor_nombre text;
alter table leads_chat add column if not exists tomado_en     timestamptz;
alter table leads_chat add column if not exists gestionado_en timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'leads_chat_estado_valido'
    ) then
        alter table leads_chat
            add constraint leads_chat_estado_valido
            check (estado in ('nuevo', 'tomado', 'contactado', 'descartado'));
    end if;
end $$;

create index if not exists leads_chat_estado_idx on leads_chat (estado, created_at desc);
create index if not exists leads_chat_asesor_idx on leads_chat (asesor_id);

notify pgrst, 'reload schema';

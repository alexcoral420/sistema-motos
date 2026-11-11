-- 031_leads_manuales.sql
--
-- Clientes que el asesor agrega a mano (/admin/leads/nuevo): los que le
-- llegan por fuera del chat del sitio (un referido, alguien que paso por
-- la sede, un mensaje directo a su WhatsApp) y que quiere llevar en el
-- mismo seguimiento que sus leads del chat (migracion 030).
--
--   origen  ya existia (001), siempre 'chat'. El lead agregado a mano
--           lleva 'asesor'.
--   canal   por donde llego ese cliente. Nulo en los leads del chat.
--
-- Un lead manual nace ya asignado a quien lo crea (estado 'tomado',
-- asesor_id, tomado_en): no pasa por la bandeja de nuevos ni dispara el
-- aviso push. El consentimiento lo declara el asesor al guardarlo
-- (autorizo_datos_basicos, fecha_consentimiento y la version de la
-- politica vigente, columnas que ya existian), y queda ademas escrito en
-- la linea de tiempo del lead (leads_notas).
--
-- Solo aditiva: el codigo en produccion no se entera de la columna.
--
-- ORDEN DE DESPLIEGUE: aplicar ANTES de desplegar el codigo (despues de
-- la 030). El codigo selecciona 'origen' y 'canal' en la bandeja.

alter table leads_chat add column if not exists canal text;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'leads_chat_canal_valido'
    ) then
        alter table leads_chat
            add constraint leads_chat_canal_valido
            check (canal is null or canal in
                   ('whatsapp', 'referido', 'presencial', 'redes', 'llamada', 'otro'));
    end if;
end $$;

notify pgrst, 'reload schema';

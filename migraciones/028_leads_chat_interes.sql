-- 028_leads_chat_interes.sql
--
-- El chat deja de pedir montos, plazos y cuotas (ya no hay calculadora) y
-- pasa a registrar que moto le interesa al cliente y como piensa pagarla.
--
--   moto_interes  la moto que el cliente nombro en la conversacion, como
--                 texto libre. Complementa a moto_id (que ya existia y se
--                 llena cuando el chat se abre desde la ficha de una moto).
--   forma_pago    financiado | contado | por_definir. 'contado' es la
--                 alerta de prioridad para el asesor.
--
-- Las columnas valor_financiar, cuota_inicial, plazo_meses y
-- cuota_calculada se conservan (tienen datos de leads anteriores); el
-- codigo simplemente deja de escribirlas.
--
-- ORDEN DE DESPLIEGUE: aplicar ANTES de desplegar el codigo. El codigo
-- inserta estas columnas; sin ellas, ningun lead del chat se guarda.

alter table leads_chat add column if not exists moto_interes text;
alter table leads_chat add column if not exists forma_pago   text;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'leads_chat_forma_pago_valida'
    ) then
        alter table leads_chat
            add constraint leads_chat_forma_pago_valida
            check (forma_pago is null or forma_pago in ('financiado', 'contado', 'por_definir'));
    end if;
end $$;

notify pgrst, 'reload schema';

-- 026: la permuta como contrato completo, registrada en un solo paso.
--
-- permutas guarda el cliente, los valores pactados y la sede, congelados
-- al registrar. Las históricas no tienen cliente ni valores (quedan en
-- NULL y no generan contrato); su sede se toma de la moto que salió.
--
-- Neto = (valor_saliente - valor_entrante) + valor_traspaso.
-- Neto > 0 paga el cliente, Neto < 0 paga la empresa, Neto = 0 sin pagos.
-- La suma de los pagos debe ser abs(Neto).
--
-- ORDEN DE DESPLIEGUE: requiere la 025. Aplicar y desplegar el código
-- enseguida: la función cambia de firma y el código anterior deja de
-- poder registrar permutas. Después: notify pgrst, 'reload schema';

begin;

-- 1. permutas: cliente, valores y sede congelados.
alter table permutas
    add column persona_id bigint references personas(id),
    add column valor_saliente bigint,
    add column valor_entrante bigint,
    add column valor_traspaso bigint,
    add column sede_id bigint references sedes(id);

update permutas p
set sede_id = m.sede_id
from motos m
where m.id = p.moto_saliente_id;

alter table permutas
    add constraint permutas_contrato_completo
    check (num_nonnulls(persona_id, valor_saliente, valor_entrante, valor_traspaso) in (0, 4)),
    add constraint permutas_valores_validos
    check (valor_saliente > 0 and valor_entrante > 0 and valor_traspaso >= 0);

create index if not exists idx_permutas_sede on permutas (sede_id);

-- 2. pagos: pertenecen a una venta, una compra o una permuta, exactamente una.
--    Sin cascade, igual que compra_id.
alter table pagos add column permuta_id bigint references permutas(id);
create index if not exists idx_pagos_permuta on pagos (permuta_id);

alter table pagos drop constraint pagos_una_operacion;
alter table pagos
    add constraint pagos_una_operacion
    check (num_nonnulls(venta_id, compra_id, permuta_id) = 1);

-- 3. La función. Cambia de firma: sin el DROP, Postgres dejaría viva la
--    versión anterior como una sobrecarga.
drop function registrar_permuta_moto(bigint, jsonb, bigint, text, bigint, text, jsonb);

create function registrar_permuta_moto(
    p_moto_saliente_id bigint,
    p_moto jsonb,
    p_usuario_id bigint,
    p_usuario_nombre text,
    p_asesor_id bigint,
    p_asesor_nombre text,
    p_datos_contrato jsonb,
    p_persona_id bigint,
    p_valor_saliente bigint,
    p_valor_entrante bigint,
    p_valor_traspaso bigint,
    p_pagos jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
    v_saliente    motos%rowtype;
    v_entrante_id bigint;
    v_permuta_id  bigint;
    v_placa       text := nullif(upper(trim(p_moto->>'placa')), '');
    v_neto        bigint;
    v_a_pagar     bigint;
    v_suma_pagos  bigint;
begin
    if p_moto_saliente_id is null
       or p_usuario_id is null or nullif(p_usuario_nombre, '') is null
       or p_asesor_id is null or nullif(p_asesor_nombre, '') is null
       or p_persona_id is null
       or nullif(p_moto->>'marca', '') is null
       or nullif(p_moto->>'modelo', '') is null then
        raise exception 'Faltan datos de la permuta (motos, cliente, quién registra o qué asesor la hizo).';
    end if;

    if v_placa is null then
        raise exception 'Falta la placa de la moto que entra.';
    end if;

    if p_datos_contrato is null
       or nullif(trim(p_datos_contrato->>'numero_chasis'), '') is null
       or nullif(trim(p_datos_contrato->>'numero_motor'), '') is null then
        raise exception 'Faltan el número de chasis o de motor de la moto que entra.';
    end if;

    if nullif(trim(p_datos_contrato->>'propietario_registrado'), '') is null then
        raise exception 'Falta el propietario registrado de la moto que entra.';
    end if;

    if p_valor_saliente is null or p_valor_saliente <= 0
       or p_valor_entrante is null or p_valor_entrante <= 0
       or p_valor_traspaso is null or p_valor_traspaso < 0 then
        raise exception 'Los valores de la permuta no son válidos.';
    end if;

    -- Pagos: la suma debe ser abs(Neto); con Neto 0 no hay pagos.
    if p_pagos is null or jsonb_typeof(p_pagos) <> 'array' then
        raise exception 'Los pagos de la permuta no son válidos.';
    end if;

    v_neto := (p_valor_saliente - p_valor_entrante) + p_valor_traspaso;
    v_a_pagar := abs(v_neto);

    if exists (select 1 from jsonb_array_elements(p_pagos) p
               where coalesce((p->>'monto')::bigint, 0) <= 0) then
        raise exception 'Todos los pagos deben tener un monto mayor a cero.';
    end if;

    select coalesce(sum((p->>'monto')::bigint), 0) into v_suma_pagos
    from jsonb_array_elements(p_pagos) p;

    if v_suma_pagos <> v_a_pagar then
        raise exception 'Los pagos suman %, pero deben sumar % (neto de la permuta).',
            v_suma_pagos, v_a_pagar;
    end if;

    -- Bloquea la saliente: un segundo registro simultáneo espera a este.
    select * into v_saliente from motos where id = p_moto_saliente_id for update;
    if not found then
        raise exception 'La moto que sale no existe.';
    end if;

    if v_saliente.estado <> 'disponible' then
        raise exception 'La moto que sale ya no está disponible: su estado es %.', v_saliente.estado;
    end if;

    -- El contrato identifica las dos motos: la saliente necesita su RUNT.
    if not exists (
        select 1 from datos_contrato
        where moto_id = p_moto_saliente_id
          and nullif(trim(numero_chasis), '') is not null
          and nullif(trim(numero_motor), '') is not null
    ) then
        raise exception 'La moto que sale no tiene cargado el RUNT (chasis y motor).';
    end if;

    -- La placa de la entrante no puede estar ya en inventario.
    if exists (
        select 1 from motos
        where upper(placa) = v_placa and estado <> 'vendido'
    ) then
        raise exception 'Ya hay una moto en inventario con la placa %.', v_placa;
    end if;

    -- Precio y kilometraje pueden ir vacíos: se completan en su detalle
    -- antes de publicarla.
    insert into motos (
        marca, modelo, anio, color, cilindraje, kilometraje, placa,
        descripcion, soat, tecno, sede_id, estado, precio
    ) values (
        p_moto->>'marca',
        p_moto->>'modelo',
        (p_moto->>'anio')::int,
        p_moto->>'color',
        (p_moto->>'cilindraje')::int,
        (p_moto->>'kilometraje')::int,
        v_placa,
        coalesce(p_moto->>'descripcion', ''),
        p_moto->>'soat',
        p_moto->>'tecno',
        v_saliente.sede_id,
        'por_publicar',
        (p_moto->>'precio')::bigint
    )
    returning id into v_entrante_id;

    -- Datos del contrato: RUNT más los datos cargados a mano. Quedan en
    -- la moto para cuando se venda después.
    insert into datos_contrato (
        moto_id, placa, licencia_transito, estado_vehiculo, tipo_servicio,
        clase_vehiculo, marca, linea, modelo, color, numero_serie,
        numero_motor, numero_chasis, numero_vin, cilindraje,
        tipo_carroceria, tipo_combustible, fecha_matricula,
        autoridad_transito, manifiesto_aduana, fecha_manifiesto,
        propietario_registrado
    )
    select
        v_entrante_id, r.placa, r.licencia_transito, r.estado_vehiculo, r.tipo_servicio,
        r.clase_vehiculo, r.marca, r.linea, r.modelo, r.color, r.numero_serie,
        r.numero_motor, r.numero_chasis, r.numero_vin, r.cilindraje,
        r.tipo_carroceria, r.tipo_combustible, r.fecha_matricula,
        r.autoridad_transito, r.manifiesto_aduana, r.fecha_manifiesto,
        r.propietario_registrado
    from jsonb_populate_record(null::datos_contrato, p_datos_contrato) r;

    update motos set estado = 'vendido' where id = p_moto_saliente_id;

    -- Descripciones, valores y sede se congelan al registrar.
    insert into permutas (
        moto_entrante_id, moto_saliente_id,
        descripcion_entrante, descripcion_saliente,
        usuario_id, usuario_nombre, asesor_id, asesor_nombre,
        persona_id, valor_saliente, valor_entrante, valor_traspaso, sede_id
    ) values (
        v_entrante_id, p_moto_saliente_id,
        concat_ws(' ', p_moto->>'marca', p_moto->>'modelo', p_moto->>'anio'),
        concat_ws(' ', v_saliente.marca, v_saliente.modelo, v_saliente.anio),
        p_usuario_id, p_usuario_nombre, p_asesor_id, p_asesor_nombre,
        p_persona_id, p_valor_saliente, p_valor_entrante, p_valor_traspaso,
        v_saliente.sede_id
    )
    returning id into v_permuta_id;

    insert into pagos (permuta_id, metodo, entidad, monto, descripcion)
    select
        v_permuta_id,
        p->>'metodo',
        nullif(p->>'entidad', ''),
        (p->>'monto')::bigint,
        nullif(p->>'descripcion', '')
    from jsonb_array_elements(p_pagos) p;

    return jsonb_build_object(
        'permuta_id', v_permuta_id,
        'moto_entrante_id', v_entrante_id
    );
end;
$$;

-- 4. Permisos: solo el panel (service_role), nunca la key pública.
revoke execute on function registrar_permuta_moto(bigint, jsonb, bigint, text, bigint, text, jsonb, bigint, bigint, bigint, bigint, jsonb)
    from public, anon, authenticated;
grant execute on function registrar_permuta_moto(bigint, jsonb, bigint, text, bigint, text, jsonb, bigint, bigint, bigint, bigint, jsonb)
    to service_role;

commit;

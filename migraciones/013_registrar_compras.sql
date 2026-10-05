-- 013: registro atómico de compras.
--
-- registrar_compra crea, en una sola transacción, la moto (siempre
-- 'por_publicar'), sus datos de contrato, la compra, sus pagos y, si la
-- empresa asume parte del traspaso, el gasto correspondiente. Si algo
-- falla, no queda nada.
--
-- Reparto de responsabilidades: el servicio en Python valida formatos,
-- normaliza, resuelve la persona y da mensajes claros. Esta función
-- protege las reglas que, si se rompen, dejan datos inconsistentes.
--
-- Traspaso: valor_traspaso es el total; traspaso_vendedor, la parte que
-- asume el vendedor (se le descuenta del pago). La parte de la empresa
-- no se guarda: se deduce, y se registra como gasto de la moto.
-- Prenda, comparendos, impuestos: son PAGOS del precio a un tercero,
-- no gastos. La suma de todos los pagos = precio_compra - traspaso_vendedor.

begin;

-- 1. motos: fallar cerrado.
--    Una inserción que olvide el estado crea una moto oculta, no pública.
--    Una moto sin sede falla, en vez de caer en la sede 1.
alter table motos alter column estado set default 'por_publicar';
alter table motos alter column estado set not null;
alter table motos alter column sede_id drop default;

-- 2. compras: traspaso. Nulls solo en compras históricas (las dos juntas).
alter table compras
    add column valor_traspaso bigint,
    add column traspaso_vendedor bigint;
alter table compras
    add constraint compras_traspaso_check check (
        (valor_traspaso is null and traspaso_vendedor is null)
        or (valor_traspaso >= 0
            and traspaso_vendedor >= 0
            and traspaso_vendedor <= valor_traspaso)
    );

-- 3. pagos: descripción para pagos a terceros
--    (ej: "Comparendo 12345 Secretaría de Movilidad").
alter table pagos add column descripcion text;

-- 4. La función.
create or replace function registrar_compra(
    p_moto jsonb,
    p_datos_contrato jsonb,
    p_compra jsonb,
    p_pagos jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
    v_moto_id           bigint;
    v_compra_id         bigint;
    v_sede_id           bigint := (p_compra->>'sede_id')::bigint;
    v_usuario_id        bigint := (p_compra->>'usuario_id')::bigint;
    v_precio            bigint := (p_compra->>'precio_compra')::bigint;
    v_valor_traspaso    bigint := coalesce((p_compra->>'valor_traspaso')::bigint, 0);
    v_traspaso_vendedor bigint := coalesce((p_compra->>'traspaso_vendedor')::bigint, 0);
    v_placa             text   := nullif(upper(trim(p_moto->>'placa')), '');
    v_a_pagar           bigint;
    v_suma_pagos        bigint;
    v_gasto_empresa     bigint;
begin
    -- Obligatorios de la compra.
    if v_sede_id is null
       or v_usuario_id is null
       or nullif(p_compra->>'usuario_nombre', '') is null
       or (p_compra->>'asesor_id') is null
       or nullif(p_compra->>'asesor_nombre', '') is null
       or (p_compra->>'vendedor_id') is null
       or v_precio is null or v_precio <= 0 then
        raise exception 'Faltan datos obligatorios de la compra.';
    end if;

    -- Traspaso.
    if v_valor_traspaso < 0
       or v_traspaso_vendedor < 0
       or v_traspaso_vendedor > v_valor_traspaso then
        raise exception 'El traspaso que asume el vendedor no puede superar el valor total del traspaso.';
    end if;

    -- Pagos: al menos uno, y todos positivos.
    if p_pagos is null
       or jsonb_typeof(p_pagos) <> 'array'
       or jsonb_array_length(p_pagos) = 0 then
        raise exception 'La compra debe tener al menos un pago.';
    end if;

    if exists (select 1 from jsonb_array_elements(p_pagos) p
               where coalesce((p->>'monto')::bigint, 0) <= 0) then
        raise exception 'Todos los pagos deben tener un monto mayor a cero.';
    end if;

    -- La suma de los pagos cuadra con lo que se paga.
    v_a_pagar := v_precio - v_traspaso_vendedor;
    select sum((p->>'monto')::bigint) into v_suma_pagos
    from jsonb_array_elements(p_pagos) p;

    if v_suma_pagos <> v_a_pagar then
        raise exception 'Los pagos suman %, pero se deben pagar % (precio % menos traspaso del vendedor %).',
            v_suma_pagos, v_a_pagar, v_precio, v_traspaso_vendedor;
    end if;

    -- La placa no puede estar ya en inventario.
    if v_placa is not null and exists (
        select 1 from motos
        where upper(placa) = v_placa and estado <> 'vendido'
    ) then
        raise exception 'Ya hay una moto en inventario con la placa %.', v_placa;
    end if;

    -- Moto: el estado lo decide la función, no quien llama.
    -- Precio de venta nulo: se define al publicar.
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
        v_sede_id,
        'por_publicar',
        null
    )
    returning id into v_moto_id;

    -- Datos del contrato (RUNT + manifiesto), tomados por nombre de columna.
    insert into datos_contrato (
        moto_id, placa, licencia_transito, estado_vehiculo, tipo_servicio,
        clase_vehiculo, marca, linea, modelo, color, numero_serie,
        numero_motor, numero_chasis, numero_vin, cilindraje,
        tipo_carroceria, tipo_combustible, fecha_matricula,
        autoridad_transito, manifiesto_aduana, fecha_manifiesto
    )
    select
        v_moto_id, r.placa, r.licencia_transito, r.estado_vehiculo, r.tipo_servicio,
        r.clase_vehiculo, r.marca, r.linea, r.modelo, r.color, r.numero_serie,
        r.numero_motor, r.numero_chasis, r.numero_vin, r.cilindraje,
        r.tipo_carroceria, r.tipo_combustible, r.fecha_matricula,
        r.autoridad_transito, r.manifiesto_aduana, r.fecha_manifiesto
    from jsonb_populate_record(null::datos_contrato, p_datos_contrato) r;

    -- Compra. La descripción se congela como texto, igual que en ventas.
    insert into compras (
        moto_id, descripcion, placa,
        usuario_id, usuario_nombre, asesor_id, asesor_nombre,
        sede_id, vendedor_id, precio_compra,
        valor_traspaso, traspaso_vendedor, propietario_registrado
    ) values (
        v_moto_id,
        concat_ws(' ', p_moto->>'marca', p_moto->>'modelo', p_moto->>'anio'),
        v_placa,
        v_usuario_id,
        p_compra->>'usuario_nombre',
        (p_compra->>'asesor_id')::bigint,
        p_compra->>'asesor_nombre',
        v_sede_id,
        (p_compra->>'vendedor_id')::bigint,
        v_precio,
        v_valor_traspaso,
        v_traspaso_vendedor,
        nullif(p_compra->>'propietario_registrado', '')
    )
    returning id into v_compra_id;

    -- Pagos (al vendedor o a terceros: prenda, comparendo, impuesto...).
    insert into pagos (compra_id, metodo, entidad, monto, descripcion)
    select
        v_compra_id,
        p->>'metodo',
        nullif(p->>'entidad', ''),
        (p->>'monto')::bigint,
        nullif(p->>'descripcion', '')
    from jsonb_array_elements(p_pagos) p;

    -- La parte del traspaso que asume la empresa es un gasto de la moto.
    v_gasto_empresa := v_valor_traspaso - v_traspaso_vendedor;
    if v_gasto_empresa > 0 then
        insert into gastos (
            moto_id, placa, tipo, concepto, monto, fecha_gasto,
            origen, usuario_id, sede_id
        ) values (
            v_moto_id, v_placa, 'traspaso',
            'Traspaso asumido por la empresa (compra #' || v_compra_id || ')',
            v_gasto_empresa, now(), 'compra', v_usuario_id, v_sede_id
        );
    end if;

    return jsonb_build_object('moto_id', v_moto_id, 'compra_id', v_compra_id);
end;
$$;

-- 5. Permisos: en Supabase, toda función de public queda expuesta por la
--    API. Solo el panel (service_role) puede ejecutarla; la key pública no.
revoke execute on function registrar_compra(jsonb, jsonb, jsonb, jsonb)
    from public, anon, authenticated;
grant execute on function registrar_compra(jsonb, jsonb, jsonb, jsonb)
    to service_role;

commit;
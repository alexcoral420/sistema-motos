-- 014: traspaso negociado en ventas y guardado atómico del detalle.
--
-- Espejo de compras: valor_traspaso es el total; traspaso_comprador, la
-- parte que asume el comprador (la paga además del precio). La parte de
-- la empresa no se guarda: se deduce, y se registra como gasto de la moto.
-- Regla: suma de pagos = precio_venta + traspaso_comprador.
--
-- guardar_detalle_venta reemplaza el "borrar pagos e insertar" del
-- código, que no era atómico: con un doble clic podía duplicar pagos, y
-- si la inserción fallaba la venta quedaba sin pagos. Ahora todo ocurre
-- en una transacción, y la fila de la venta se bloquea mientras tanto.
--
-- A diferencia de compras, el detalle de una venta se puede volver a
-- guardar. Por eso el gasto de traspaso queda vinculado a la venta
-- (gastos.venta_id) y se reemplaza en cada guardado, en vez de acumularse.

begin;

-- 1. ventas: parte del traspaso que asume el comprador.
alter table ventas add column traspaso_comprador bigint;

-- Ventas existentes: el contrato decía que el comprador asumía todo.
update ventas
set traspaso_comprador = valor_traspaso
where valor_traspaso is not null;

alter table ventas
    add constraint ventas_traspaso_check check (
        (valor_traspaso is null and traspaso_comprador is null)
        or (valor_traspaso >= 0
            and traspaso_comprador >= 0
            and traspaso_comprador <= valor_traspaso)
    );

-- 2. gastos: vínculo con la venta que lo originó.
alter table gastos add column venta_id bigint references ventas(id);

-- 3. La función.
create or replace function guardar_detalle_venta(
    p_venta_id bigint,
    p_comprador_id bigint,
    p_precio_venta bigint,
    p_valor_traspaso bigint,
    p_traspaso_comprador bigint,
    p_pagos jsonb,
    p_usuario_id bigint
)
returns void
language plpgsql
set search_path = public
as $$
declare
    v_venta         ventas%rowtype;
    v_a_pagar       bigint;
    v_suma_pagos    bigint;
    v_gasto_empresa bigint;
begin
    -- Bloquea la venta: un segundo guardado simultáneo espera a este.
    select * into v_venta from ventas where id = p_venta_id for update;
    if not found then
        raise exception 'La venta no existe.';
    end if;

    if p_comprador_id is null then
        raise exception 'Falta el comprador.';
    end if;

    if p_precio_venta is null or p_precio_venta <= 0 then
        raise exception 'El precio de venta debe ser mayor a cero.';
    end if;

    if p_valor_traspaso is null or p_traspaso_comprador is null
       or p_valor_traspaso < 0
       or p_traspaso_comprador < 0
       or p_traspaso_comprador > p_valor_traspaso then
        raise exception 'El traspaso que asume el comprador no puede superar el valor total del traspaso.';
    end if;

    if p_pagos is null
       or jsonb_typeof(p_pagos) <> 'array'
       or jsonb_array_length(p_pagos) = 0 then
        raise exception 'La venta debe tener al menos un pago.';
    end if;

    if exists (select 1 from jsonb_array_elements(p_pagos) p
               where coalesce((p->>'monto')::bigint, 0) <= 0) then
        raise exception 'Todos los pagos deben tener un monto mayor a cero.';
    end if;

    v_a_pagar := p_precio_venta + p_traspaso_comprador;
    select sum((p->>'monto')::bigint) into v_suma_pagos
    from jsonb_array_elements(p_pagos) p;

    if v_suma_pagos <> v_a_pagar then
        raise exception 'Los pagos suman %, pero el comprador debe pagar % (precio % más traspaso a su cargo %).',
            v_suma_pagos, v_a_pagar, p_precio_venta, p_traspaso_comprador;
    end if;

    -- Detalle de la venta.
    update ventas set
        comprador_id       = p_comprador_id,
        precio_venta       = p_precio_venta,
        valor_traspaso     = p_valor_traspaso,
        traspaso_comprador = p_traspaso_comprador,
        detalle_completo   = true
    where id = p_venta_id;

    -- Pagos: se reemplazan.
    delete from pagos where venta_id = p_venta_id;
    insert into pagos (venta_id, metodo, entidad, monto, descripcion)
    select
        p_venta_id,
        p->>'metodo',
        nullif(p->>'entidad', ''),
        (p->>'monto')::bigint,
        nullif(p->>'descripcion', '')
    from jsonb_array_elements(p_pagos) p;

    -- Gasto de traspaso de la empresa: se reemplaza, no se acumula.
    delete from gastos where venta_id = p_venta_id and tipo = 'traspaso';
    v_gasto_empresa := p_valor_traspaso - p_traspaso_comprador;
    if v_gasto_empresa > 0 then
        insert into gastos (
            moto_id, placa, tipo, concepto, monto, fecha_gasto,
            origen, usuario_id, sede_id, venta_id
        ) values (
            v_venta.moto_id, v_venta.placa, 'traspaso',
            'Traspaso asumido por la empresa (venta #' || p_venta_id || ')',
            v_gasto_empresa, now(), 'venta', p_usuario_id,
            v_venta.sede_id, p_venta_id
        );
    end if;
end;
$$;

-- 4. Permisos: solo el panel (service_role), nunca la key pública.
revoke execute on function guardar_detalle_venta(bigint, bigint, bigint, bigint, bigint, jsonb, bigint)
    from public, anon, authenticated;
grant execute on function guardar_detalle_venta(bigint, bigint, bigint, bigint, bigint, jsonb, bigint)
    to service_role;

commit;
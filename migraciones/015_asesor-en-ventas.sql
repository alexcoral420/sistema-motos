-- 015: asesor en ventas y registro atómico de la venta.
--
-- Espejo de compras: usuario_id/usuario_nombre = quién registró;
-- asesor_id/asesor_nombre = quién hizo la venta. Las ventas históricas
-- las registró el propio asesor, así que se rellenan con usuario_*.
--
-- registrar_venta_moto reemplaza "marcar vendida + registrar venta",
-- dos operaciones sin transacción: si la segunda fallaba, la moto quedaba
-- vendida sin venta; y dos clics simultáneos podían vender dos veces la
-- misma moto. Ahora la fila de la moto se bloquea y todo ocurre junto.
--
-- Compatible con el código en producción: las columnas nuevas son
-- opcionales y la función nueva no reemplaza a nada todavía.

begin;

-- 1. ventas: quién hizo la venta.
alter table ventas
    add column asesor_id bigint references usuarios(id),
    add column asesor_nombre text;

update ventas set asesor_id = usuario_id, asesor_nombre = usuario_nombre;

-- 2. La función.
create or replace function registrar_venta_moto(
    p_moto_id bigint,
    p_usuario_id bigint,
    p_usuario_nombre text,
    p_asesor_id bigint,
    p_asesor_nombre text
)
returns bigint
language plpgsql
set search_path = public
as $$
declare
    v_moto     motos%rowtype;
    v_venta_id bigint;
begin
    if p_usuario_id is null or nullif(p_usuario_nombre, '') is null
       or p_asesor_id is null or nullif(p_asesor_nombre, '') is null then
        raise exception 'Faltan datos de la venta (quién registra o qué asesor vendió).';
    end if;

    -- Bloquea la moto: una segunda venta simultánea espera a esta.
    select * into v_moto from motos where id = p_moto_id for update;
    if not found then
        raise exception 'La moto no existe.';
    end if;

    if v_moto.estado not in ('disponible', 'reservado') then
        raise exception 'La moto no se puede vender: su estado es %.', v_moto.estado;
    end if;

    update motos set estado = 'vendido' where id = p_moto_id;

    -- La descripción se congela como texto, igual que antes.
    insert into ventas (
        moto_id, descripcion, placa,
        usuario_id, usuario_nombre, asesor_id, asesor_nombre, sede_id
    ) values (
        p_moto_id,
        concat_ws(' ', v_moto.marca, v_moto.modelo, v_moto.anio),
        v_moto.placa,
        p_usuario_id, p_usuario_nombre, p_asesor_id, p_asesor_nombre,
        v_moto.sede_id
    )
    returning id into v_venta_id;

    return v_venta_id;
end;
$$;

-- 3. Permisos: solo el panel (service_role), nunca la key pública.
revoke execute on function registrar_venta_moto(bigint, bigint, text, bigint, text)
    from public, anon, authenticated;
grant execute on function registrar_venta_moto(bigint, bigint, text, bigint, text)
    to service_role;

commit;
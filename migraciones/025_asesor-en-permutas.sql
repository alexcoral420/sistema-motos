-- 025: asesor en permutas y registro atómico de la permuta.
--
-- Espejo de ventas (015): usuario_id/usuario_nombre = quién registró;
-- asesor_id/asesor_nombre = quién hizo el negocio. Hasta ahora solo el
-- asesor registraba permutas, así que las históricas se rellenan con
-- usuario_*. Desde aquí registran admin y encargado de sede, y el
-- reporte "Permutas por asesor" cuenta por asesor_nombre.
--
-- registrar_permuta_moto reemplaza tres escrituras sueltas (crear la
-- moto entrante, marcar vendida la saliente, insertar la permuta): si una
-- fallaba quedaban datos a medias, y dos registros simultáneos podían
-- entregar dos veces la misma moto. Ahora la saliente se bloquea y todo
-- ocurre en una transacción.
--
-- Compatible con el código en producción: las columnas nuevas son
-- opcionales y la función nueva no reemplaza a nada todavía.

begin;

-- 1. permutas: quién hizo el negocio.
alter table permutas
    add column asesor_id bigint references usuarios(id),
    add column asesor_nombre text;

update permutas set asesor_id = usuario_id, asesor_nombre = usuario_nombre;

-- 2. La función.
--    p_moto: datos de la moto entrante ya validados en Python. La sede y
--    el estado los decide la función: la entrante queda en la sede de la
--    saliente (donde se cerró el negocio) y siempre 'por_publicar'.
--    p_datos_contrato: lo parseado del RUNT de la entrante, o null si no
--    se pegó (se puede cargar después desde el detalle de la moto).
create or replace function registrar_permuta_moto(
    p_moto_saliente_id bigint,
    p_moto jsonb,
    p_usuario_id bigint,
    p_usuario_nombre text,
    p_asesor_id bigint,
    p_asesor_nombre text,
    p_datos_contrato jsonb default null
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
begin
    if p_moto_saliente_id is null
       or p_usuario_id is null or nullif(p_usuario_nombre, '') is null
       or p_asesor_id is null or nullif(p_asesor_nombre, '') is null
       or nullif(p_moto->>'marca', '') is null
       or nullif(p_moto->>'modelo', '') is null then
        raise exception 'Faltan datos de la permuta (motos, quién registra o qué asesor la hizo).';
    end if;

    -- Bloquea la saliente: un segundo registro simultáneo espera a este.
    select * into v_saliente from motos where id = p_moto_saliente_id for update;
    if not found then
        raise exception 'La moto que sale no existe.';
    end if;

    if v_saliente.estado <> 'disponible' then
        raise exception 'La moto que sale ya no está disponible: su estado es %.', v_saliente.estado;
    end if;

    -- La placa de la entrante no puede estar ya en inventario.
    if v_placa is not null and exists (
        select 1 from motos
        where upper(placa) = v_placa and estado <> 'vendido'
    ) then
        raise exception 'Ya hay una moto en inventario con la placa %.', v_placa;
    end if;

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

    -- Datos del contrato (RUNT), tomados por nombre de columna. El
    -- manifiesto de aduana no viene del RUNT: se carga a mano después.
    if p_datos_contrato is not null then
        insert into datos_contrato (
            moto_id, placa, licencia_transito, estado_vehiculo, tipo_servicio,
            clase_vehiculo, marca, linea, modelo, color, numero_serie,
            numero_motor, numero_chasis, numero_vin, cilindraje,
            tipo_carroceria, tipo_combustible, fecha_matricula,
            autoridad_transito
        )
        select
            v_entrante_id, r.placa, r.licencia_transito, r.estado_vehiculo, r.tipo_servicio,
            r.clase_vehiculo, r.marca, r.linea, r.modelo, r.color, r.numero_serie,
            r.numero_motor, r.numero_chasis, r.numero_vin, r.cilindraje,
            r.tipo_carroceria, r.tipo_combustible, r.fecha_matricula,
            r.autoridad_transito
        from jsonb_populate_record(null::datos_contrato, p_datos_contrato) r;
    end if;

    update motos set estado = 'vendido' where id = p_moto_saliente_id;

    -- Las descripciones se congelan como texto, igual que antes.
    insert into permutas (
        moto_entrante_id, moto_saliente_id,
        descripcion_entrante, descripcion_saliente,
        usuario_id, usuario_nombre, asesor_id, asesor_nombre
    ) values (
        v_entrante_id, p_moto_saliente_id,
        concat_ws(' ', p_moto->>'marca', p_moto->>'modelo', p_moto->>'anio'),
        concat_ws(' ', v_saliente.marca, v_saliente.modelo, v_saliente.anio),
        p_usuario_id, p_usuario_nombre, p_asesor_id, p_asesor_nombre
    )
    returning id into v_permuta_id;

    return jsonb_build_object(
        'permuta_id', v_permuta_id,
        'moto_entrante_id', v_entrante_id
    );
end;
$$;

-- 3. Permisos: solo el panel (service_role), nunca la key pública.
revoke execute on function registrar_permuta_moto(bigint, jsonb, bigint, text, bigint, text, jsonb)
    from public, anon, authenticated;
grant execute on function registrar_permuta_moto(bigint, jsonb, bigint, text, bigint, text, jsonb)
    to service_role;

commit;

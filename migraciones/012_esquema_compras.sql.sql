-- 012: esquema del módulo de compras.
-- compras pasa de registro de atribución a registro administrativo.
-- usuario_id/usuario_nombre: quién registró. asesor_id/asesor_nombre:
-- quién hizo el negocio. Los pagos pertenecen a una venta o a una
-- compra, nunca a las dos.
--
-- Compatible con el código en producción: todo lo nuevo es opcional.
-- asesor_id NO es not null todavía porque /comprar sigue activo; la
-- obligatoriedad la garantiza la función de registro, y el not null
-- se agrega cuando /comprar se retire.

begin;

-- 1. Compras: columnas nuevas. Nullable por las compras históricas.
alter table compras
    add column sede_id bigint references sedes(id),
    add column asesor_id bigint references usuarios(id),
    add column asesor_nombre text,
    add column vendedor_id bigint references personas(id),
    add column precio_compra bigint check (precio_compra > 0),
    add column propietario_registrado text,
    add column venta_permuta_id bigint references ventas(id);

-- Históricas: quien registró es el asesor, y la sede es la de la moto.
update compras set asesor_id = usuario_id, asesor_nombre = usuario_nombre;
update compras c set sede_id = m.sede_id
from motos m where m.id = c.moto_id;

-- 2. Manifiesto de aduana: solo motos importadas, se carga a mano.
--    (datos_contrato ya tiene unicidad por moto: idx_datos_contrato_moto)
alter table datos_contrato
    add column manifiesto_aduana text,
    add column fecha_manifiesto text;

-- 3. Pagos: pertenecen a una venta o a una compra, exactamente una.
--    Sin cascade: no se puede borrar una compra que tiene pagos.
alter table pagos add column compra_id bigint references compras(id);
alter table pagos alter column venta_id drop not null;
alter table pagos
    add constraint pagos_una_operacion
    check (num_nonnulls(venta_id, compra_id) = 1);

-- 4. Limpieza: la 011 agregó personas_cedula_key, que duplica este
--    índice heredado de compradores. Queda uno solo.
drop index idx_compradores_cedula;

commit;
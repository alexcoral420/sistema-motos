-- 011: compradores pasa a ser personas. Una misma persona puede ser
-- comprador en una venta y vendedor en una compra. El rol lo da la
-- columna que la referencia (ventas.comprador_id, compras.vendedor_id),
-- no la tabla.

begin;

alter table compradores rename to personas;
alter table personas rename constraint compradores_pkey to personas_pkey;
alter table personas add constraint personas_cedula_key unique (cedula);

commit;
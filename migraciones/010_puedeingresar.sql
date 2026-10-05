-- 011: separa "pertenece a la empresa" (activo) de "puede entrar al
-- panel" (puede_ingresar). Un asesor puede seguir activo (sus links del
-- catálogo y su atribución funcionan) sin acceso al sistema.

begin;

alter table usuarios
    add column puede_ingresar boolean not null default true;

commit;
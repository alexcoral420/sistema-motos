-- 010: ciclo de publicación de motos.
-- Agrega el estado 'por_publicar' (moto comprada, aún no lista para el
-- catálogo), restringe los estados válidos y registra cuándo se publicó.

begin;

-- 1. Cuándo pasó la moto a 'disponible'. Null en las motos existentes:
--    la vista usa created_at como respaldo para ellas.
alter table motos add column publicada_en timestamptz;

-- 2. Estados válidos. Debe coincidir con ESTADOS_MOTO en inventario.py.
alter table motos add constraint motos_estado_check
    check (estado in ('por_publicar', 'disponible', 'reservado', 'vendido'));

-- 3. La ventana de "moto nueva" se cuenta desde la publicación, no desde
--    la creación. Mismas columnas que antes: solo cambia es_reciente.
create or replace view catalogo_ordenado as
 SELECT m.id,
    m.created_at,
    m.marca,
    m.modelo,
    m.anio,
    m.color,
    m.precio,
    m.kilometraje,
    m.foto_url,
    m.foto_path,
    m.video_path,
    m.estado,
    m.descripcion,
    m.soat,
    m.tecno,
    m.placa,
    m.cilindraje,
    m.sede_id,
    s.nombre AS sede_nombre,
    s.direccion AS sede_direccion,
    COALESCE(count(i.id) FILTER (WHERE i.created_at > (now() - '15 days'::interval)), 0::bigint) AS consultas_recientes,
    COALESCE(m.publicada_en, m.created_at) > (now() - '8 days'::interval) AS es_reciente
   FROM motos m
     LEFT JOIN sedes s ON s.id = m.sede_id
     LEFT JOIN intenciones i ON i.moto_id = m.id
  WHERE m.estado = 'disponible'::text
  GROUP BY m.id, s.nombre, s.direccion;

commit;
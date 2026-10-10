-- Asociación moto <-> giro 360°.
-- Las fotos del giro viven en el bucket en: giro/<id de la moto>/001.webp ... 024.webp
-- Esta columna marca qué motos tienen el giro cargado. Se activa con un
-- UPDATE manual tras subir las 24 fotos (a futuro, un botón en el admin).
ALTER TABLE motos ADD COLUMN tiene_giro BOOLEAN NOT NULL DEFAULT false;

-- Moto del piloto: ya tiene su giro subido (se migrará su carpeta a /giro/<id>/).
UPDATE motos SET tiene_giro = true WHERE placa = 'MYG73H';

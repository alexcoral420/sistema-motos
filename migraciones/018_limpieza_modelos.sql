-- =====================================================================
-- Migración 018 — Limpieza de modelos/marcas de motos hacia el catálogo
--                 canónico.
--
-- NOTA IMPORTANTE (drift):
--   Esta transformación YA fue aplicada manualmente a PRODUCCIÓN el
--   2026-10-26 desde el editor SQL de Supabase. Se registra aquí como
--   migración para que el historial sea reproducible (un entorno nuevo,
--   o la restauración de un backup previo a la limpieza, quedan igual
--   que producción al correr las migraciones en orden).
--
--   NO re-aplicar en producción: ya está aplicada. De todos modos el
--   UPDATE es IDEMPOTENTE (solo toca filas que aún difieren del valor
--   canónico), así que correrlo de nuevo no causa daño.
--
--   Las consultas de PREVIEW (PASO 1 y PASO 2) que se usaron para
--   revisar antes de escribir viven en el histórico; aquí queda solo
--   el UPDATE final. Los registros que NO matchearon el mapa se tratan
--   a mano en la sección "REGISTROS MANUALES" al final de este archivo.
-- =====================================================================

WITH mapa(dmarca,dmodelo,cil,new_marca,new_modelo) AS (VALUES
  ('AIMA','TIGERX6(ELECTRICA)',NULL::int,'AIMA','Tiger X6 (eléctrica)'),
  ('AKT','AK125 NKDR',NULL::int,'AKT','NKD 125'),
  ('AKT','AK125CR4',NULL::int,'AKT','CR4 125'),
  ('AKT','AK125RL',NULL::int,'AKT','125 RL'),
  ('AKT','AK162CR4',NULL::int,'AKT','CR4 150'),
  ('AKT','AK200DS',NULL::int,'AKT','TT Dual Sport 200'),
  ('AKT','AK200TTR',NULL::int,'AKT','TTR 200'),
  ('AKT','CR4',125::int,'AKT','CR4 125'),
  ('AKT','CR4',200::int,'AKT','CR4 200'),
  ('AKT','DINAMIC PRO',NULL::int,'AKT','Dinamic Pro 125'),
  ('AKT','NKD',NULL::int,'AKT','NKD 125'),
  ('AKT','NKD125',NULL::int,'AKT','NKD 125'),
  ('AKT','TT DUAL SPORT',NULL::int,'AKT','TT Dual Sport 200'),
  ('AKT','TT OURING',NULL::int,'AKT','TT Touring 250'),
  ('AKT','TT SPORT',NULL::int,'AKT','TT Sport 200'),
  ('AKT','TTR',NULL::int,'AKT','TTR 200'),
  ('AKT','TTR125',NULL::int,'AKT','TTR 125'),
  ('APACHE','APACHE160',NULL::int,'TVS','Apache RTR 160'),
  ('APACHE RTR','2023',NULL::int,'TVS','Apache RTR 160'),
  ('AUTECO','DINAMIC',NULL::int,'AUTECO','Dinamic 125'),
  ('AUTECO','TWIST KYMCO',NULL::int,'AUTECO','Twist City 125'),
  ('BAJAJ','APACHE RTR 200',NULL::int,'TVS','Apache RTR 200'),
  ('BAJAJ','BOXER',NULL::int,'BAJAJ','Boxer CT 100'),
  ('BAJAJ','BOXER CT',NULL::int,'BAJAJ','Boxer CT 100'),
  ('BAJAJ','DISCOVER',NULL::int,'BAJAJ','Discover 150'),
  ('BAJAJ','DISVOVER',NULL::int,'BAJAJ','Discover 150'),
  ('BAJAJ','DOMINAR',250::int,'BAJAJ','Dominar 250'),
  ('BAJAJ','DOMINAR',400::int,'BAJAJ','Dominar 400'),
  ('BAJAJ','DOMINAR 400',NULL::int,'BAJAJ','Dominar 400'),
  ('BAJAJ','DOMINAR UG',NULL::int,'BAJAJ','Dominar 400'),
  ('BAJAJ','N160',NULL::int,'BAJAJ','Pulsar N160'),
  ('BAJAJ','NS',125::int,'BAJAJ','Pulsar 125'),
  ('BAJAJ','NS',200::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','NS CARBURADA',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','NS FI',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','NS200',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR',135::int,'BAJAJ','Pulsar 135 LS'),
  ('BAJAJ','PULSAR',150::int,'BAJAJ','Pulsar NS 150'),
  ('BAJAJ','PULSAR',180::int,'BAJAJ','Pulsar 180'),
  ('BAJAJ','PULSAR 135 LS',NULL::int,'BAJAJ','Pulsar 135 LS'),
  ('BAJAJ','PULSAR 200 NS PULSARMANIA',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR ARE 200',NULL::int,'BAJAJ','Pulsar RS 200'),
  ('BAJAJ','PULSAR FI NEO',NULL::int,'BAJAJ','Pulsar 180'),
  ('BAJAJ','PULSAR N250',NULL::int,'BAJAJ','Pulsar N250'),
  ('BAJAJ','PULSAR NS',125::int,'BAJAJ','Pulsar 125'),
  ('BAJAJ','PULSAR NS',150::int,'BAJAJ','Pulsar NS 150'),
  ('BAJAJ','PULSAR NS',160::int,'BAJAJ','Pulsar NS 160'),
  ('BAJAJ','PULSAR NS',200::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR NS 200',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR NS 200 FI STD',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR NS FI',160::int,'BAJAJ','Pulsar NS 160'),
  ('BAJAJ','PULSAR NS FI',160::int,'BAJAJ','Pulsar NS 160'),
  ('BAJAJ','PULSAR NS FI',200::int,'BAJAJ','Pulsar NS 200'),
  ('BAJAJ','PULSAR NS160 FI',NULL::int,'BAJAJ','Pulsar NS 160'),
  ('BAJAJ','PULSAR RS 200 ABS',NULL::int,'BAJAJ','Pulsar RS 200'),
  ('BENELLI','180 S',NULL::int,'BENELLI','TNT 180S'),
  ('BENELLI','180S',NULL::int,'BENELLI','TNT 180S'),
  ('BENELLI','BENELLI',NULL::int,'BENELLI','TNT 150'),
  ('BENELLI','BENELLI S',NULL::int,'BENELLI','TNT 150'),
  ('BENELLI','S',NULL::int,'BENELLI','TNT 180S'),
  ('BENELLI','TNT',NULL::int,'BENELLI','TNT 150'),
  ('BENELLI','TNT150I',NULL::int,'BENELLI','TNT 150'),
  ('BENELLI','TNT25N',NULL::int,'BENELLI','TNT 250'),
  ('BENELLI','TRK',NULL::int,'BENELLI','TRK 251'),
  ('BMW','GS',NULL::int,'BMW','G 310 GS'),
  ('DL','DL',NULL::int,'SUZUKI','V-Strom 650'),
  ('HERO','DASH',NULL::int,'HERO','Dash 125'),
  ('HERO','HUNK',125::int,'HERO','Hunk 150'),
  ('HERO','HUNK',160::int,'HERO','Hunk 160'),
  ('HERO','HUNK 160 4V',NULL::int,'HERO','Hunk 160'),
  ('HERO','HUNK 4V',NULL::int,'HERO','Hunk 160'),
  ('HERO','HUNK FI',NULL::int,'HERO','Hunk 160'),
  ('HERO','SPLENDOR',NULL::int,'HERO','Splendor 110'),
  ('HERO','SPLENDOR ISMAER',NULL::int,'HERO','Splendor 110'),
  ('HERO','XPULSE',NULL::int,'HERO','Xpulse 200'),
  ('HONDA','CB',NULL::int,'HONDA','CB190R'),
  ('HONDA','CB 125',NULL::int,'HONDA','CB125F'),
  ('HONDA','CB 160F DLX',NULL::int,'HONDA','CB160F'),
  ('HONDA','CB 190 REPSOL',NULL::int,'HONDA','CB190R'),
  ('HONDA','CB F',NULL::int,'HONDA','CB125F'),
  ('HONDA','CB MAX II',NULL::int,'HONDA','CB125F'),
  ('HONDA','CB125F E3',NULL::int,'HONDA','CB125F'),
  ('HONDA','CB160',NULL::int,'HONDA','CB160F'),
  ('HONDA','CB190 2.0',NULL::int,'HONDA','CB190R'),
  ('HONDA','CB300F',NULL::int,'HONDA','CB300F'),
  ('HONDA','NAVI',NULL::int,'HONDA','Navi'),
  ('HONDA','PCX DLX',NULL::int,'HONDA','PCX 150'),
  ('HONDA','XR',150::int,'HONDA','XR 150L'),
  ('HONDA','XR',190::int,'HONDA','XR 190'),
  ('HUSQVARNA','SVARTPILEN',NULL::int,'HUSQVARNA','Svartpilen 401'),
  ('JAJAJ','NS200',NULL::int,'BAJAJ','Pulsar NS 200'),
  ('KAWASAKI','ER250C',NULL::int,'KAWASAKI','Ninja 250'),
  ('KAWASAKI','EX650ECF',NULL::int,'KAWASAKI','Ninja 650'),
  ('KAWASAKI','NINJA',NULL::int,'KAWASAKI','Ninja 250'),
  ('KAWASAKI','Z',NULL::int,'KAWASAKI','Z250'),
  ('KTM','ADVENTURE',NULL::int,'KTM','390 Adventure'),
  ('KTM','DUKE',NULL::int,'KTM','Duke 200'),
  ('KYMCO','AGILITY',NULL::int,'KYMCO','Agility 125'),
  ('KYMCO','TWIST CITY EU3',NULL::int,'AUTECO','Twist City 125'),
  ('KYMCO','TWISTE CITY',NULL::int,'AUTECO','Twist City 125'),
  ('ROYAL ENFIELD','HIMALAYAN',NULL::int,'ROYAL ENFIELD','Himalayan 411'),
  ('SUZUKI','ACCES',NULL::int,'SUZUKI','Access 125'),
  ('SUZUKI','BURGMAN',NULL::int,'SUZUKI','Burgman 125'),
  ('SUZUKI','BURMAN',NULL::int,'SUZUKI','Burgman 125'),
  ('SUZUKI','DL',NULL::int,'SUZUKI','V-Strom 650'),
  ('SUZUKI','FR',NULL::int,'SUZUKI','FR 90'),
  ('SUZUKI','GIXXER',150::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GIXXER',180::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GIXXER',250::int,'SUZUKI','Gixxer 250'),
  ('SUZUKI','GIXXER 150',NULL::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GIXXER 250',NULL::int,'SUZUKI','Gixxer 250'),
  ('SUZUKI','GIXXER FI',NULL::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GIXXER FI 150',NULL::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GIXXER SF',150::int,'SUZUKI','Gixxer SF 150'),
  ('SUZUKI','GIXXER SF',250::int,'SUZUKI','Gixxer SF 250'),
  ('SUZUKI','GIXXER SF 250',NULL::int,'SUZUKI','Gixxer SF 250'),
  ('SUZUKI','GIXXER\N',NULL::int,'SUZUKI','Gixxer 150'),
  ('SUZUKI','GN',NULL::int,'SUZUKI','GN 125'),
  ('SUZUKI','GS R',NULL::int,'SUZUKI','GSX-R 150'),
  ('SUZUKI','GSX 150',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX R',NULL::int,'SUZUKI','GSX-R 150'),
  ('SUZUKI','GSX S',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX-S',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX-S 150',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX-S150 ABS',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX150',NULL::int,'SUZUKI','GSX-S 150'),
  ('SUZUKI','GSX500',NULL::int,'SUZUKI','GSX 500'),
  ('SUZUKI','INTRUDER',NULL::int,'SUZUKI','Intruder 150'),
  ('SUZUKI','V STROM SX',NULL::int,'SUZUKI','V-Strom SX 250'),
  ('SUZUKY','DL650',NULL::int,'SUZUKI','V-Strom 650'),
  ('THRILLER','150',NULL::int,'HERO','Thriller 150'),
  ('TVS','APACHE',160::int,'TVS','Apache RTR 160'),
  ('TVS','APACHE',200::int,'TVS','Apache RTR 200'),
  ('TVS','APACHE 160 2V',NULL::int,'TVS','Apache RTR 160'),
  ('TVS','APACHE 2V',NULL::int,'TVS','Apache RTR 180'),
  ('TVS','APACHE 4V',160::int,'TVS','Apache RTR 160'),
  ('TVS','APACHE 4V',200::int,'TVS','Apache RTR 200'),
  ('TVS','APACHE RTR',160::int,'TVS','Apache RTR 160'),
  ('TVS','APACHE RTR',180::int,'TVS','Apache RTR 180'),
  ('TVS','APACHE RTR 160',NULL::int,'TVS','Apache RTR 160'),
  ('TVS','APACHE RTR 200',NULL::int,'TVS','Apache RTR 200'),
  ('TVS','APACHE RTR 200 4V XCONNECT',NULL::int,'TVS','Apache RTR 200'),
  ('TVS','APCHE',NULL::int,'TVS','Apache RTR 200'),
  ('TVS','NTORQ',NULL::int,'TVS','Ntorq 125'),
  ('TVS','RAIDER',NULL::int,'TVS','Raider 125'),
  ('TVS','RAIDER FI',NULL::int,'TVS','Raider 125'),
  ('VICTORY','ARIZONA',150::int,'VICTORY','MRX 150'),
  ('VICTORY','ARIZONA',200::int,'VICTORY','MRX 200'),
  ('VICTORY','ARIZONA MRX',NULL::int,'VICTORY','MRX 200'),
  ('VICTORY','BLACK',150::int,'VICTORY','MRX 150'),
  ('VICTORY','BLACK',200::int,'VICTORY','MRX 200'),
  ('VICTORY','BOMBER',125::int,'VICTORY','Bomber 125'),
  ('VICTORY','BOMBER',150::int,'VICTORY','Bomber 150'),
  ('VICTORY','BOMBER',180::int,'VICTORY','Bomber 180'),
  ('VICTORY','LIFE',NULL::int,'VICTORY','Life 125'),
  ('VICTORY','LIVE 1',NULL::int,'VICTORY','Life 125'),
  ('VICTORY','MRX',150::int,'VICTORY','MRX 150'),
  ('VICTORY','MRX',200::int,'VICTORY','MRX 200'),
  ('VICTORY','MRX ARIZONA',NULL::int,'VICTORY','MRX 200'),
  ('VICTORY','NITRO',NULL::int,'VICTORY','Nitro 150'),
  ('VICTORY','NITRO R',NULL::int,'VICTORY','Nitro 150'),
  ('VICTORY','ONE ST',NULL::int,'VICTORY','One ST 100'),
  ('VICTORY','VENO',NULL::int,'VICTORY','Venom 150'),
  ('VICTORY','VENOM',NULL::int,'VICTORY','Venom 150'),
  ('VICTORY','VENOM 18',NULL::int,'VICTORY','Venom 200'),
  ('VICTORY','VENOM14',NULL::int,'VICTORY','Venom 150'),
  ('YAMAHA','AEROX S',NULL::int,'YAMAHA','Aerox 155'),
  ('YAMAHA','FAZZER',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ 2.5',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ 25',NULL::int,'YAMAHA','FZ 250'),
  ('YAMAHA','FZ 3.0',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ FAZER 150',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ S',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ-S',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ15 A',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ15S',NULL::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZ250',NULL::int,'YAMAHA','FZ 250'),
  ('YAMAHA','FZN',150::int,'YAMAHA','FZ-S 150'),
  ('YAMAHA','FZN',250::int,'YAMAHA','FZ 250'),
  ('YAMAHA','FZN250',NULL::int,'YAMAHA','FZ 250'),
  ('YAMAHA','FZN250-A',NULL::int,'YAMAHA','FZ 250'),
  ('YAMAHA','MT 03',NULL::int,'YAMAHA','MT-03'),
  ('YAMAHA','MT 09',NULL::int,'YAMAHA','MT-09'),
  ('YAMAHA','MT 15',NULL::int,'YAMAHA','MT-15'),
  ('YAMAHA','MT-03',NULL::int,'YAMAHA','MT-03'),
  ('YAMAHA','MT03',NULL::int,'YAMAHA','MT-03'),
  ('YAMAHA','R15',NULL::int,'YAMAHA','YZF-R15'),
  ('YAMAHA','R3',NULL::int,'YAMAHA','YZF-R3'),
  ('YAMAHA','R3320',NULL::int,'YAMAHA','YZF-R3'),
  ('YAMAHA','XTZ',NULL::int,'YAMAHA','XTZ 125'),
  ('YAMAHA','XTZ150-2 (XTZ150)',NULL::int,'YAMAHA','XTZ 150'),
  ('YAMAHA','YBR',NULL::int,'YAMAHA','YBR 125'),
  ('YAMAHA','YZF 155 (YZF-R15)',NULL::int,'YAMAHA','YZF-R15'),
  ('YAMAHA','YZF-R15',NULL::int,'YAMAHA','YZF-R15')
)
UPDATE motos m SET marca = x.new_marca, modelo = x.new_modelo
FROM mapa x
WHERE upper(btrim(regexp_replace(m.marca,'\s+',' ','g'))) = x.dmarca AND upper(btrim(regexp_replace(m.modelo,'\s+',' ','g'))) = x.dmodelo AND (x.cil IS NULL OR m.cilindraje = x.cil)
  AND (m.marca IS DISTINCT FROM x.new_marca OR m.modelo IS DISTINCT FROM x.new_modelo);

-- =====================================================================
-- REGISTROS MANUALES (no matchearon el mapa automático)
-- ---------------------------------------------------------------------
-- Estas 7 filas se corrigieron (o deben corregirse) a mano en prod,
-- por id. Completá cada línea con el valor canónico REAL que quedó en
-- producción (podés copiarlo con el SELECT de abajo) y descomentala.
-- Así la migración refleja el estado limpio final, no solo el masivo.
--
--   SELECT id, marca, modelo, cilindraje, estado
--   FROM motos WHERE id IN (226,188,307,261,319,312,169)
--   ORDER BY id;
--
-- CF Moto (ids 226, 188, 307):
-- UPDATE motos SET marca='CFMOTO', modelo='<modelo canónico>' WHERE id=226;
-- UPDATE motos SET marca='CFMOTO', modelo='<modelo canónico>' WHERE id=188;
-- UPDATE motos SET marca='CFMOTO', modelo='<modelo canónico>' WHERE id=307;
-- Domina / 2021 (id 261):
-- UPDATE motos SET marca='<marca>', modelo='<modelo>' WHERE id=261;
-- Suzuki / 2023 (id 319):
-- UPDATE motos SET marca='SUZUKI', modelo='<modelo>' WHERE id=319;
-- Victory / 2023 (id 312):
-- UPDATE motos SET marca='VICTORY', modelo='<modelo>' WHERE id=312;
-- Yamaha SZ15RR (id 169):
-- UPDATE motos SET marca='YAMAHA', modelo='SZ-RR 150' WHERE id=169;
-- =====================================================================
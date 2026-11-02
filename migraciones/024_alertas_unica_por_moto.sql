-- Una sola alerta de SOAT y una de tecnomecánica por moto.
--
-- El servidor ya hace "si existe, actualiza; si no, crea", pero sin este
-- índice dos envíos casi simultáneos (un doble toque) podrían crear dos
-- alertas del mismo tipo para la misma moto, y en la Fase B saldrían
-- avisos duplicados. Con el índice, el segundo insert falla con 23505 y
-- el servidor actualiza la alerta que ya existe.
--
-- Parcial a propósito: no limita tipos que podrían repetirse por moto
-- más adelante (p. ej. 'otro'), y la de crédito no tiene moto (NULL).
--
-- Seguro de aplicar: hasta esta versión no había forma de crear alertas
-- de SOAT ni tecno, así que no hay duplicados previos.

CREATE UNIQUE INDEX IF NOT EXISTS alertas_moto_tipo_unica
    ON alertas (moto_usuario_id, tipo)
    WHERE tipo IN ('soat', 'tecno');

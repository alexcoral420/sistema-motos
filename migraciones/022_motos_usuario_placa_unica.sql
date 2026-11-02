-- "Mi espacio", Capa 1: una placa no se repite dentro de la cuenta de un
-- motero (casi siempre es un error de digitación). Parcial: las motos sin
-- placa no cuentan, se pueden registrar varias.
--
-- Es por motero, no global: dos cuentas pueden registrar la misma placa
-- (una moto vendida, un error de otro) y ninguna debe enterarse de la otra.
--
-- La app guarda la placa ya normalizada (mayúsculas, sin espacios ni
-- guiones; validadores.validar_placa_moto), así que comparar el valor tal
-- cual basta. Si se viola, PostgREST devuelve el código 23505 y el servicio
-- lo traduce a "Ya tienes una moto con esa placa".

CREATE UNIQUE INDEX IF NOT EXISTS motos_usuario_placa_unica
    ON motos_usuario (usuario_id, placa)
    WHERE placa IS NOT NULL;

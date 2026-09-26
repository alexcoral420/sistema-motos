-- ============================================================
-- Migración 007: Datos de contrato (captura desde el RUNT)
-- ============================================================
-- Fase 1 del módulo de contratos: el encargado de sede pega el texto
-- de la consulta RUNT en el detalle de la moto, un parser lo organiza
-- y se guarda aquí. La Fase 2 (generar el Word) lee de esta tabla.
--
-- Todos los campos son TEXT a propósito: fidelidad al RUNT. El
-- contrato debe decir exactamente lo que dice el registro oficial
-- (ceros a la izquierda en números de motor, fechas en su formato
-- original, etc.), sin conversiones que puedan alterarlo.
--
-- Un registro por moto: el índice único en moto_id permite hacer
-- upsert al re-cargar el texto (se reemplaza, no se duplica).
-- ============================================================

CREATE TABLE IF NOT EXISTS datos_contrato (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    moto_id           BIGINT NOT NULL REFERENCES motos(id),
    placa             TEXT,
    licencia_transito TEXT,
    estado_vehiculo   TEXT,
    tipo_servicio     TEXT,
    clase_vehiculo    TEXT,
    marca             TEXT,
    linea             TEXT,
    modelo            TEXT,
    color             TEXT,
    numero_serie      TEXT,
    numero_motor      TEXT,
    numero_chasis     TEXT,
    numero_vin        TEXT,
    cilindraje        TEXT,
    tipo_carroceria   TEXT,
    tipo_combustible  TEXT,
    fecha_matricula   TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_datos_contrato_moto ON datos_contrato (moto_id);

-- Seguridad: mismo patrón que el esquema inicial. Solo el backend
-- (service_role) lee y escribe; el cliente anónimo no ve nada.
ALTER TABLE datos_contrato ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON datos_contrato FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON datos_contrato TO service_role;

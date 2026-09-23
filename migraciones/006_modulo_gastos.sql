-- ============================================================
-- Migración 006: Módulo de gastos
-- ============================================================
-- Registra los gastos de cada moto (taller, repuestos, lavadero)
-- para poder calcular rentabilidad más adelante (venta - gastos).
-- Independiente del módulo de ventas: no toca esas tablas.
--
-- placa y sede_id se CONGELAN como snapshot de la moto al momento del
-- gasto, igual que en ventas: si la moto se borra, el gasto sigue
-- siendo legible, y el aislamiento por sede no depende de un JOIN.
-- ============================================================

CREATE TABLE IF NOT EXISTS gastos (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    moto_id       BIGINT REFERENCES motos(id) ON DELETE SET NULL,
    placa         TEXT,
    tipo          TEXT NOT NULL,
    concepto      TEXT NOT NULL,
    monto         BIGINT NOT NULL,
    fecha_gasto   TIMESTAMPTZ NOT NULL,
    origen        TEXT NOT NULL,
    orden_taller  BIGINT,
    usuario_id    BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    sede_id       BIGINT REFERENCES sedes(id) ON DELETE SET NULL
);

-- Anti-duplicado de sincronización con el taller: antes de insertar
-- un ítem, se consulta qué órdenes ya existen para esa moto. También
-- sirve para las consultas de gastos por moto.
CREATE INDEX IF NOT EXISTS idx_gastos_moto_orden ON gastos (moto_id, orden_taller);

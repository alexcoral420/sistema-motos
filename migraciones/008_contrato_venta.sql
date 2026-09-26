-- ============================================================
-- Migración 008: Contrato de venta (Fase 2)
-- ============================================================
-- Columnas que necesita la generación del contrato en Word.
-- Ambas nullable: los registros existentes siguen válidos.
-- ============================================================

-- Autoridad de tránsito donde está matriculada la moto ("Matriculado
-- en:" del contrato). Viene del RUNT; TEXT por fidelidad, como el resto.
ALTER TABLE datos_contrato ADD COLUMN IF NOT EXISTS autoridad_transito TEXT;

-- Valor del traspaso acordado con el comprador. Opcional: si es NULL,
-- el contrato lo deja en blanco.
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS valor_traspaso BIGINT;

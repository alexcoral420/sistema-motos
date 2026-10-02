-- ============================================================
-- Migración 005: Módulo de detalle de ventas
-- ============================================================
-- Extiende el registro de ventas con el detalle rico que carga
-- gerencia DESPUÉS de la verificación: comprador, pagos y precio.
--
-- NO toca el flujo existente de registrar_venta ni la verificación.
-- Las columnas nuevas quedan NULL en las ventas ya registradas.
--
-- Aislamiento por sede: se apoya en ventas.sede_id (ya existe,
-- congelada al registrar la venta). No se agrega nada para eso.
-- ============================================================

-- ----- 1. Tabla de compradores -----
CREATE TABLE IF NOT EXISTS compradores (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    nombre      TEXT NOT NULL,
    cedula      TEXT NOT NULL,
    telefono    TEXT,
    correo      TEXT
);

-- La cédula identifica al comprador. Un mismo comprador puede tener
-- varias compras, pero no debe duplicarse el registro por cédula.
CREATE UNIQUE INDEX IF NOT EXISTS idx_compradores_cedula ON compradores (cedula);

-- ----- 2. Columnas nuevas en ventas -----
-- comprador_id: quién compró (NULL hasta que gerencia complete el detalle)
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS comprador_id BIGINT REFERENCES compradores(id);

-- precio_venta: precio final real de la venta (NULL hasta el detalle)
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS precio_venta BIGINT;

-- estado: 'activa' por defecto; 'anulada' para deshacer una venta mal cargada.
-- Los reportes deben excluir las anuladas (pendiente ajustar).
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'activa';

-- detalle_completo: marca si ya se cargó comprador+pagos+precio.
-- Concepto distinto de 'estado': una venta puede estar activa pero sin detalle.
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS detalle_completo BOOLEAN NOT NULL DEFAULT false;

-- ----- 3. Tabla de pagos (varios por venta) -----
CREATE TABLE IF NOT EXISTS pagos (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    venta_id    BIGINT NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    metodo      TEXT NOT NULL,
    entidad     TEXT,
    monto       BIGINT NOT NULL
);

-- Los pagos de una venta se consultan juntos: índice por venta.
CREATE INDEX IF NOT EXISTS idx_pagos_venta ON pagos (venta_id);

-- ----- 4. Índices de apoyo -----
-- El módulo lista ventas pendientes de detalle, filtradas por sede.
CREATE INDEX IF NOT EXISTS idx_ventas_pendientes ON ventas (detalle_completo, sede_id);
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Sistema Universal Motors: a production Flask app for a used-motorcycle dealership in Bogotá (two locations). It manages inventory, a public filterable catalog, sales/purchase/trade-in operations, and an AI-driven WhatsApp financing-lead assistant. Live at universalmotors.online. Not a toy project — real business data, real users daily. See `README.md` for the full design rationale (security model, AI assistant safety guarantees, personal-data compliance, deliberate architectural decisions) — read it before making non-trivial changes; this file only covers what you need to move fast day-to-day.

## Commands

```bash
# Setup
python -m venv venv
.\venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt

# Run locally (reads FLASK_ENV from .env, defaults to development)
python run.py                       # serves on http://127.0.0.1:5000

# Create a user (interactive prompt: usuario, rol, sede, password)
python scripts/crear_usuario.py

# Production (Railway, via Procfile)
gunicorn run:app --bind 0.0.0.0:$PORT
```

There is no test suite (`tests/` is empty, no pytest config) and no configured linter — this is documented as known technical debt in the README, not an oversight. Verification is manual; when changing behavior, check it by running the app.

Required `.env` vars are listed in `.env.example`: `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `SUPABASE_ANON_KEY`, `ANTHROPIC_API_KEY`, `CLAVE_CIFRADO` (Fernet key for sensitive fields — irrecoverable if lost, never commit it), `WHATSAPP_CONTACTO`, plus Twilio/Meta WhatsApp Cloud API credentials.

## Architecture

Strict layered flow, one direction only:

```
route (blueprint)  →  servicio  →  repositorio  →  Supabase
   orchestrates        decides       queries         stores
```

- **Routes** (`app/admin`, `app/publico`, `app/api`, `app/auth`, `app/webhook`): receive the request, delegate, return the response. No validation, no queries here.
- **Services** (`app/servicios/`): business logic and input validation live here. This is where criteria live — what counts as a valid filter, what data to request from a customer, when a lead gets saved.
- **Repositories** (`app/db/repositorios.py`): talk to Supabase. No business vocabulary — receive already-validated, already-translated data.

Respect this separation when adding features: a change to catalog filtering, for example, should touch only a service, not routes or the repository.

### Blueprints (registered in `app/__init__.py`)

- `publico` — catalog, moto detail, financing landing, chat
- `admin` — management panel (`/admin` prefix, role-protected)
- `auth` — login/session
- `api` — REST API for external integrations (n8n), API-key authenticated, CSRF-exempt
- `webhook` — inbound messaging events (WhatsApp/Meta), CSRF-exempt

### Two Supabase clients, different privilege (`app/db/cliente.py`)

- `get_supabase_publico()` — anon key, read-only, subject to RLS. Used by the public catalog, the most exposed surface.
- `get_supabase_admin()` — service_role key, bypasses RLS, read/write. Only used from code already behind login.

When adding a table, follow the existing pattern: enable RLS, revoke from `anon`, grant explicitly to `service_role`.

### Auth and roles

Session-based auth (`app/auth/`). Roles: `admin`, `asesor`, `gerencia`, `encargado_sede`. Enforced with `@requiere_rol("admin", "asesor", ...)` and `@requiere_login` from `app/auth/decorators.py`, applied per-route in `app/admin/routes.py`. No session → redirect to login (401-equivalent); wrong role → `403`. **Identity always comes from `session`, never from a submitted form field** — e.g. when recording a sale, the acting user is read from the session so one advisor can't attribute an action to another by editing the HTML. UI role-based hiding is cosmetic only; the real gate is server-side.

The `api` blueprint uses `@requiere_api_key` (`app/auth/api_key.py`) instead of sessions.

### Single sources of truth (recurring pattern in this codebase)

When a decision would otherwise be duplicated across places, it's centralized once:

- `app/servicios/campos_credito.py` — declares what data is requested from a lead (field name, validation type, required, sensitive/encrypted, active). The assistant's prompt, the extractor's schema, and server-side validation are all generated from this one list. Adding/removing a lead field means editing only this file. Fields can be defined but `activo: False` — e.g. credit-bureau data (regulated under Colombian Law 1266) is built but deliberately disabled pending legal review.
- `config.WHATSAPP_CONTACTO` — the public contact number, injected into every template via a context processor in `app/__init__.py`.
- `app/servicios/catalogo.py` — filter ranges (brand, displacement, year, price), feeding validation, the query, and the UI labels from one place.

### AI assistant (`app/servicios/asistente.py`, `extractor.py`)

Key design point: **the AI converses, the server decides.** The model never directly executes a save. An independent extractor reads the conversation and reports structured data (a bounded task: read and return JSON); the server then validates and decides whether to persist it. Consent for data collection is verified twice — once by the extractor, and independently by a pure-Python function that re-scans the actual conversation for an explicit question-then-affirmative-answer pattern; a mismatch blocks the save. The assistant is prevented from quoting financing installment amounts (a past incident produced plausible-but-wrong numbers); the server scans outgoing replies and strips any quoted figures rather than trusting the prompt alone. The model's context is restricted to public information only (aggregate inventory, locations, hours) — never leads, users, or other customers' data.

### Data model notes

Core tables (see `migraciones/001_esquema_inicial.sql` for the full initial schema): `sedes`, `contactos`, `politicas_privacidad`, `usuarios`, `motos`, `fotos_motos`, `intenciones`, `ventas`, `compras`, `permutas`, `leads_chat`, `conversaciones`, `mensajes`.

- Sensitive/financial fields are encrypted with Fernet (`app/seguridad/cifrado.py`); the key (`CLAVE_CIFRADO`) lives only in env vars, never in the database or repo.
- Privacy consent is versioned: `politicas_privacidad` archives each policy version's full text with a SHA-256 hash, and each lead records which version it consented to.
- Sales/purchase records intentionally denormalize: they freeze the moto description and seller name as text at time of transaction (in addition to keeping the original foreign keys), so historical records stay readable even if the moto is deleted or a user is renamed.

### Migrations

SQL migrations live in `migraciones/`, numbered sequentially. **Note:** there are currently two files both numbered `005_` (`005_modulo_detalle_ventas.sql` and `005_normalizar_papeles_nuevos.sql`) — check existing numbering carefully before adding a new one to avoid a collision. Not all schema changes have historically been captured as migrations (some were applied directly against the database), which has caused at least one schema/code drift incident — when changing the schema, always add a migration file rather than applying changes out-of-band.

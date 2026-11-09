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

```bash
# Tests (from the project root)
python -m pytest tests/
```

There is a small pytest suite in `tests/` covering pure service logic (`test_personas.py`, `test_avaluo.py`, `test_recordatorios.py`). Tests never touch Supabase: repository functions are replaced with `monkeypatch`. `pytest.ini` sets `pythonpath = .` and `testpaths = tests`; there is no `conftest.py`. GitHub Actions (`.github/workflows/test.yml`) runs the suite on every push and PR. There is no configured linter. Coverage is far from complete, so verification is still mostly manual; when changing behavior, add or update tests for pure logic and check the rest by running the app.

Required `.env` vars are listed in `.env.example`: `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `SUPABASE_ANON_KEY`, `ANTHROPIC_API_KEY`, `CLAVE_CIFRADO` (Fernet key for sensitive fields — irrecoverable if lost, never commit it), `WHATSAPP_CONTACTO`, plus Twilio/Meta WhatsApp Cloud API credentials, and `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` for Web Push (generate once; rotating them invalidates every existing push subscription).

**`requirements.txt` is UTF-16 LE with BOM and CRLF** (a `pip freeze >` from PowerShell). Plain text tools and naive edits will corrupt it — read/write it with `encoding="utf-16"` and insert new lines without re-sorting the rest.

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
- `motero` (`app/motero/`) — "Mi espacio" for end customers: `/registro`, `/ingresar`, `/salir` (POST), `/mi-espacio`. Accounts live in **Supabase Auth**, not in `usuarios`. See below.

### "Mi espacio" del motero (`app/motero/`, migration 021)

- **Never imports `get_supabase_admin` or `app.db.repositorios`**, directly or transitively (`tests/test_cuentas_motero.py` enforces it in a clean subprocess). Data access goes through `app/motero/cliente.py`: anon key + the motero's JWT in the `Authorization` header, so RLS (`auth.uid()`) is the real gate. Queries in `app/motero/repositorio.py` don't filter by user by hand — RLS does.
- A **new Supabase client per request**, never the `get_supabase_publico()` singleton: supabase-py stores the session inside the client, and a `sign_in`/refresh on a shared client would switch every later query (the public catalog's included) to that motero's JWT.
- Tokens are stored in the Flask session (a signed, not encrypted, cookie) **Fernet-encrypted**, under `motero_*` keys (`CLAVES_SESION_MOTERO` in `app/motero/sesion.py`). `@login_requerido_motero` validates the token with Supabase Auth and refreshes it when it's expired or about to expire.
- Consent: `politica_id`/`version_politica` in `perfiles` are stamped by the `handle_new_user()` trigger (only if the signup metadata has `acepta_politica = true`); `authenticated` has no UPDATE grant on those columns.
- Shared code the motero needs lives in **neutral** modules under `app/seguridad/` — no imports from `app` (except `validadores`), `supabase` or `config` (tests check it): `validadores.py` (e.g. `validar_placa_moto`), `tiempo.py` (`HORA_COLOMBIA`, `hoy_colombia()`, `fecha_legible()`), `suscripcion_push.py` (`validar_suscripcion`, `HOSTS_PUSH`). Services like `recordatorios.py` or `contratos.py` import `repositorios`, so the motero can't import from them.
- Alerts (migration 023, `app/servicios/alertas_motero.py`): generic `alertas` model (tipo, modo fecha/km, recurrencia, umbrales); Per-type rules (recurrence, thresholds, date range, messages) live in one table, `TIPOS_ALERTA_FECHA`. Credit: monthly, 3/1 days, no moto, cap of 20 (the cap counts only credit). SOAT/tecno: per moto, yearly, 30/15/7/1 days, one of each per moto (partial unique index, migration 024; the route updates the existing one, and on a `23505` race updates the one that won). `fecha_objetivo` is an anchor that is never rewritten — each cycle's date comes from `proxima_ocurrencia()`. `dispositivos` holds the motero's push subscriptions (upsert on `usuario_id, endpoint`); `alertas_avisos` is service_role-only, for the sender.
- Sending alerts (Phase B): `scripts/enviar_alertas.py` (daily, `--dry-run`, `--hoy AAAA-MM-DD`). The decision is the pure `avisos_a_enviar()` in `alertas_motero.py`: occurrence = `proxima_ocurrencia(anchor)`, `ciclo` = that occurrence's ISO date, threshold = smallest of the row's `umbrales_dias` ≥ days left (bucket = catch-up), dedup on `(alerta_id, ciclo, umbral)`. **The job never writes to `alertas`** (rolling the anchor would drift a day-31 or Feb-29 date for good). Each notice goes to every active device of the owner; it's recorded once at least one device got it; 404/410 → `dispositivos.activo = false`; no devices or transient errors → not recorded, retried next run. Notification texts come from the `aviso` key of each `TIPOS_ALERTA_FECHA` entry.
- **The session cookie is shared** by the panel, the public site and the motero. The panel never does `session.clear()`: it removes only `CLAVES_SESION_PANEL` (`app/auth/sesion.py`). A new panel session key must be added there.

### Two Supabase clients, different privilege (`app/db/cliente.py`)

- `get_supabase_publico()` — anon key, read-only, subject to RLS. Used by the public catalog, the most exposed surface.
- `get_supabase_admin()` — service_role key, bypasses RLS, read/write. Only used from code already behind login.

When adding a table, follow the existing pattern: enable RLS, revoke from `anon`, grant explicitly to `service_role`.

**In the live database, `anon`'s RLS on `motos` only shows `estado = 'disponible'`** (applied out-of-band; the migrations still show the original `using (true)`). Any panel read that must see other states (`por_publicar`, `reservado`, `vendido`) has to use `get_supabase_admin()`; a read through the public client returns an empty result, not an error. Commits `4ced068` (panel inventory/detail) and `d74bfe5` (gastos lookup by plate) fixed cases of this.

### Auth and roles

Session-based auth (`app/auth/`). Roles: `admin`, `asesor`, `gerencia`, `encargado_sede`. Enforced with `@requiere_rol("admin", "asesor", ...)` and `@requiere_login` from `app/auth/decorators.py`, applied per-route in `app/admin/routes.py`. No session → redirect to login (401-equivalent); wrong role → `403`. **Identity always comes from `session`, never from a submitted form field** — e.g. when recording a sale, the acting user is read from the session so one advisor can't attribute an action to another by editing the HTML. UI role-based hiding is cosmetic only; the real gate is server-side.

The `api` blueprint uses `@requiere_api_key` (`app/auth/api_key.py`) instead of sessions. Deliberate exceptions, public and protected by rate limit instead because the browser calls them (a key in the page would be exposed): `GET /api/avaluo` (aggregates only) and `POST /api/recordatorios`.

### Permutas (trade-ins)

A trade-in: the customer hands over a moto (entrante, new in the system) and takes one from inventory (saliente), in one deal.

- **Who registers:** only `admin` and `encargado_sede` (`/admin/permuta`, "Nueva permuta" in the sidebar's Registrar group). The `asesor` no longer registers trade-ins.
- **Who gets credit:** the form picks the asesor who made the deal; `inventario.registrar_permuta` revalidates it with `_validar_asesor_de_venta` (active asesor of the saliente's sede). `usuario_*` = who registered (from the session), `asesor_*` = who made the deal — same split as `ventas` (015) and `compras`. The gerencia report "Permutas por asesor" (`reportes.permutas_por_usuario`) counts by `asesor_nombre`.
- **Sede:** the saliente must be within the session's sede scope (`moto_en_alcance`). The entrante always lands in the **saliente's sede** (where the deal closed), whatever the form sends, and always `por_publicar`. After registering, the user goes to the entrante's admin detail to add photos and publish it.
- **Saliente lookup:** `_moto_saliente_de_permuta` uses `repositorios.obtener_motos_por_placa` (admin client, any state, with sede name, newest first; a plate can repeat among sold motos, so the `disponible` one is chosen). Each failure has its own message, also logged: plate doesn't exist / moto not `disponible` (shows its state) / moto belongs to another sede (shows which). The single combined message used before made a real failure impossible to diagnose — keep them separate.
- **RUNT of the entrante (optional):** "Cargar del RUNT" posts the whole form to `/admin/permuta/desde-runt` (`formaction` + `formnovalidate`), which prefills the entrante fields via `prellenar_permuta_desde_runt` and keeps what was already typed (saliente plate, asesor, price). On save, the RUNT text is re-parsed server-side (never trust the displayed fields) and its plate must match the entrante's (`contratos.validar_runt_para_placa`).
- **Atomic write:** one call to the DB function `registrar_permuta_moto` (migration 025): locks the saliente (`for update`), re-checks it's `disponible`, rejects an entrante plate already in inventory, creates the entrante, inserts its `datos_contrato` if a RUNT came, marks the saliente `vendido` and inserts the `permutas` row with frozen descriptions. `P0001` errors become `ErrorValidacion` in the repository. The old three separate writes (and `marcar_como_vendida`, `_describir_moto`, `obtener_disponible_por_placa`) are gone.
- **Deploy order:** migration 025 must be applied before deploying this code (the code reads `permutas.asesor_nombre` and calls the function).
- Tests: `tests/test_permutas.py` (attribution, sede scope, asesor validation, each saliente error message, repeated plate, RUNT, report).

### Single sources of truth (recurring pattern in this codebase)

When a decision would otherwise be duplicated across places, it's centralized once:

- `app/servicios/campos_credito.py` — declares what data is requested from a lead (field name, validation type, required, sensitive/encrypted, active). The assistant's prompt, the extractor's schema, and server-side validation are all generated from this one list. Adding/removing a lead field means editing only this file. Fields can be defined but `activo: False` — e.g. credit-bureau data (regulated under Colombian Law 1266) is built but deliberately disabled pending legal review.
- `config.WHATSAPP_CONTACTO` — the public contact number, injected into every template via a context processor in `app/__init__.py`.
- `app/servicios/catalogo.py` — filter ranges (brand, displacement, year, price), feeding validation, the query, and the UI labels from one place.

### AI assistant (`app/servicios/asistente.py`, `extractor.py`)

Key design point: **the AI converses, the server decides.** The model never directly executes a save. An independent extractor reads the conversation and reports structured data (a bounded task: read and return JSON); the server then validates and decides whether to persist it. Consent for data collection is verified twice — once by the extractor, and independently by a pure-Python function that re-scans the actual conversation for an explicit question-then-affirmative-answer pattern; a mismatch blocks the save. The assistant is prevented from quoting financing installment amounts (a past incident produced plausible-but-wrong numbers); the server scans outgoing replies and strips any quoted figures rather than trusting the prompt alone. The model's context is restricted to public information only (aggregate inventory, locations, hours) — never leads, users, or other customers' data.

### PWA and push reminders

The public site is an installable PWA. `/manifest.json` and `/sw.js` are Flask routes in `app/publico/routes.py` served from the root on purpose (a service worker's scope is the folder it's served from); the SW source lives in `static/pwa/sw.js`. `app/templates/_pwa_head.html` is included only in **public** templates, never in the admin panel. Icons are generated by `scripts/generar_iconos_pwa.py` from `static/logo.png`.

`/recordatorio-soat` lets an anonymous visitor subscribe to SOAT/tecnomecánica expiry reminders (`app/servicios/recordatorios.py`):
- The device gets a secret token (kept in `localStorage`) to edit/delete its reminder now and claim it from an account later. **Only its SHA-256 is stored** (`token_hash`); the plain token leaves the server exactly once, in the POST response.
- The subscription endpoint must be `https` on an allow-listed push service host (`HOSTS_PUSH` in `app/seguridad/suscripcion_push.py`): the server will POST to it when sending, so an arbitrary URL would be an SSRF vector. The subscription is rebuilt field by field, never stored as received.
- Plate + subscription are personal data: consent is mandatory and the policy version is recorded, as with leads.
- Sending: `scripts/enviar_recordatorios.py` (daily job, its own cron). The Web Push call itself (VAPID signing, endpoint re-validation) lives in `app/servicios/push.py`, shared with the motero's alerts; each caller decides what a 404/410 deactivates. The anonymous reminders and the motero's alerts are two separate systems that coexist for now.

### Data model notes

Core tables (see `migraciones/001_esquema_inicial.sql` for the full initial schema): `sedes`, `contactos`, `politicas_privacidad`, `usuarios`, `motos`, `fotos_motos`, `intenciones`, `ventas`, `compras`, `permutas`, `leads_chat`, `conversaciones`, `mensajes`. Later migrations add, among others, `datos_contrato` (007), `recordatorios` (019), `perfiles`/`motos_usuario` (021), `dispositivos`/`alertas`/`alertas_avisos` (023) and `permutas.asesor_id`/`asesor_nombre` + `registrar_permuta_moto()` (025).

- Sensitive/financial fields are encrypted with Fernet (`app/seguridad/cifrado.py`); the key (`CLAVE_CIFRADO`) lives only in env vars, never in the database or repo.
- Privacy consent is versioned: `politicas_privacidad` archives each policy version's full text with a SHA-256 hash, and each lead records which version it consented to.
- Sales/purchase records intentionally denormalize: they freeze the moto description and seller name as text at time of transaction (in addition to keeping the original foreign keys), so historical records stay readable even if the moto is deleted or a user is renamed.

### Migrations

SQL migrations live in `migraciones/`, numbered sequentially (`NNN_descripcion.sql`; the old duplicate `005_` pair is now `005a_`/`005b_`). Before adding one, list the folder **including untracked files** — migrations are sometimes created locally before being committed — and take the next free number. Not all schema changes have historically been captured as migrations (some were applied directly against the database), which has caused at least one schema/code drift incident — when changing the schema, always add a migration file rather than applying changes out-of-band.

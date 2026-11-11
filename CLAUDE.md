# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Sistema Universal Motors: a production Flask app for a used-motorcycle dealership in Bogotá (two locations). It manages inventory, a public filterable catalog, sales/purchase/trade-in operations, and an AI-driven financing-lead assistant in the site's web chat. Live at universalmotors.online. Not a toy project — real business data, real users daily. See `README.md` for the full design rationale (security model, AI assistant safety guarantees, personal-data compliance, deliberate architectural decisions) — read it before making non-trivial changes; this file only covers what you need to move fast day-to-day.

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

Required `.env` vars are listed in `.env.example`: `SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `SUPABASE_ANON_KEY`, `ANTHROPIC_API_KEY`, `CLAVE_CIFRADO` (Fernet key for sensitive fields — irrecoverable if lost, never commit it), `WHATSAPP_CONTACTO`, `API_WEBHOOK_KEY` (the `/api` key n8n sends; the name is historical) with the optional `API_WEBHOOK_KEY_ANTERIOR` (rotation only, see "External API"), and `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` for Web Push (generate once; rotating them invalidates every existing push subscription).

**`requirements.txt` is UTF-16 LE with BOM and CRLF** (a `pip freeze >` from PowerShell). Plain text tools and naive edits will corrupt it — read/write it with `encoding="utf-16"` and insert new lines without re-sorting the rest.

## Architecture

Strict layered flow, one direction only:

```
route (blueprint)  →  servicio  →  repositorio  →  Supabase
   orchestrates        decides       queries         stores
```

- **Routes** (`app/admin`, `app/publico`, `app/api`, `app/auth`): receive the request, delegate, return the response. No validation, no queries here.
- **Services** (`app/servicios/`): business logic and input validation live here. This is where criteria live — what counts as a valid filter, what data to request from a customer, when a lead gets saved.
- **Repositories** (`app/db/repositorios.py`): talk to Supabase. No business vocabulary — receive already-validated, already-translated data.

Respect this separation when adding features: a change to catalog filtering, for example, should touch only a service, not routes or the repository.

### Blueprints (registered in `app/__init__.py`)

- `publico` — catalog, moto detail, financing landing, chat
- `admin` — management panel (`/admin` prefix, role-protected)
- `auth` — login/session
- `api` — REST API for external integrations (n8n), API-key authenticated, CSRF-exempt
- `motero` (`app/motero/`) — "Mi espacio" for end customers: `/registro`, `/ingresar`, `/salir` (POST), `/mi-espacio`. Accounts live in **Supabase Auth**, not in `usuarios`. See below.

### "Mi espacio" del motero (`app/motero/`, migration 021)

- **Never imports `get_supabase_admin` or `app.db.repositorios`**, directly or transitively (`tests/test_cuentas_motero.py` enforces it in a clean subprocess). Data access goes through `app/motero/cliente.py`: anon key + the motero's JWT in the `Authorization` header, so RLS (`auth.uid()`) is the real gate. Queries in `app/motero/repositorio.py` don't filter by user by hand — RLS does.
- A **new Supabase client per request**, never the `get_supabase_publico()` singleton: supabase-py stores the session inside the client, and a `sign_in`/refresh on a shared client would switch every later query (the public catalog's included) to that motero's JWT.
- Tokens are stored in the Flask session (a signed, not encrypted, cookie) **Fernet-encrypted**, under `motero_*` keys (`CLAVES_SESION_MOTERO` in `app/motero/sesion.py`). `@login_requerido_motero` validates the token with Supabase Auth and refreshes it when it's expired or about to expire.
- Consent: `politica_id`/`version_politica` in `perfiles` are stamped by the `handle_new_user()` trigger (only if the signup metadata has `acepta_politica = true`); `authenticated` has no UPDATE grant on those columns.
- Shared code the motero needs lives in **neutral** modules under `app/seguridad/` — no imports from `app` (except `validadores`), `supabase` or `config` (tests check it): `validadores.py` (e.g. `validar_placa_moto`), `tiempo.py` (`HORA_COLOMBIA`, `hoy_colombia()`, `fecha_legible()`), `suscripcion_push.py` (`validar_suscripcion`, `HOSTS_PUSH`). Services like `recordatorios.py` or `contratos.py` import `repositorios`, so the motero can't import from them.
- Alerts (migration 023, `app/servicios/alertas_motero.py`): generic `alertas` model (tipo, modo fecha/km, recurrencia, umbrales); Per-type rules (recurrence, thresholds, date range, messages) live in one table, `TIPOS_ALERTA_FECHA`. Credit: monthly, 3/1 days, no moto, cap of 20 (the cap counts only credit). SOAT/tecno: per moto, yearly, 30/15/7/1 days, one of each per moto (partial unique index, migration 024; the route updates the existing one, and on a `23505` race updates the one that won). `fecha_objetivo` is an anchor that is never rewritten — each cycle's date comes from `proxima_ocurrencia()`. `dispositivos` holds the motero's push subscriptions (upsert on `usuario_id, endpoint`); `alertas_avisos` is service_role-only, for the sender.
- Sending alerts (Phase B): `scripts/enviar_alertas.py` (daily, `--dry-run`, `--hoy AAAA-MM-DD`). The decision is the pure `avisos_a_enviar()` in `alertas_motero.py`: occurrence = `proxima_ocurrencia(anchor)`, `ciclo` = that occurrence's ISO date, threshold = smallest of the row's `umbrales_dias` ≥ days left (bucket = catch-up), dedup on `(alerta_id, ciclo, umbral)`. **The job never writes to `alertas`** (rolling the anchor would drift a day-31 or Feb-29 date for good). Each notice goes to every active device of the owner; it's recorded once at least one device got it; 404/410 → `dispositivos.activo = false`; no devices or transient errors → not recorded, retried next run. Notification texts come from the `aviso` key of each `TIPOS_ALERTA_FECHA` entry.
- **The session cookie is shared** by the panel, the public site and the motero. The panel never does `session.clear()`: it removes only `CLAVES_SESION_PANEL` (`app/auth/sesion.py`). A new panel session key must be added there. The panel login makes the cookie permanent (`iniciar_sesion_duradera`): `PERMANENT_SESSION_LIFETIME` = `config.DIAS_SESION_PANEL` = 10 days. Flask refreshes the cookie's expiry on every request, so the real cap is `session["panel_ingreso"]` (login time), checked per request by `sesion_vencida()` inside `verificar_usuario_habilitado`: 10 days **from login**, not from last use. `cerrar_sesion_panel()` turns `session.permanent` back off.

### Two Supabase clients, different privilege (`app/db/cliente.py`)

- `get_supabase_publico()` — anon key, read-only, subject to RLS. Used by the public catalog, the most exposed surface.
- `get_supabase_admin()` — service_role key, bypasses RLS, read/write. Only used from code already behind login.

When adding a table, follow the existing pattern: enable RLS, revoke from `anon`, grant explicitly to `service_role`.

**In the live database, `anon`'s RLS on `motos` only shows `estado = 'disponible'`** (applied out-of-band; the migrations still show the original `using (true)`). Any panel read that must see other states (`por_publicar`, `reservado`, `vendido`) has to use `get_supabase_admin()`; a read through the public client returns an empty result, not an error. Commits `4ced068` (panel inventory/detail) and `d74bfe5` (gastos lookup by plate) fixed cases of this.

### Auth and roles

Session-based auth (`app/auth/`). Roles: `admin`, `asesor`, `gerencia`, `encargado_sede`. Enforced with `@requiere_rol("admin", "asesor", ...)` and `@requiere_login` from `app/auth/decorators.py`, applied per-route in `app/admin/routes.py`. No session → redirect to login (401-equivalent); wrong role → `403`. **Identity always comes from `session`, never from a submitted form field** — e.g. when recording a sale, the acting user is read from the session so one advisor can't attribute an action to another by editing the HTML. UI role-based hiding is cosmetic only; the real gate is server-side.

The `api` blueprint uses `@requiere_api_key` (`app/auth/api_key.py`) instead of sessions. Deliberate exceptions, public and protected by rate limit instead because the browser calls them (a key in the page would be exposed): `GET /api/avaluo` (aggregates only) and `POST /api/recordatorios`.

### External API (`/api`, consumed only by n8n)

- **Key and rotation** (`app/auth/api_key.py`): `Authorization: Bearer <key>` against `API_WEBHOOK_KEY`; without it every keyed route answers `503` (fail-closed, even if the previous key is set). `API_WEBHOOK_KEY_ANTERIOR` is optional and both are accepted while it exists. To rotate with no downtime: copy the current key to `_ANTERIOR` → put the new one in `API_WEBHOOK_KEY` and deploy → change it in n8n → delete `_ANTERIOR` once the log stops showing `consumidor=n8n(anterior)`.
- **Per-request log**: an `after_request` on the blueprint writes one line per request, rejections included: `API | METHOD rule | status | ip=… | consumidor=…`, with `consumidor` ∈ `n8n`, `n8n(anterior)`, `sin_llave`, `llave_invalida`, `sin_configurar`, `publico`. It logs the route **rule**, never the query string, the body or the key. Logger `auditoria.api` is pinned to INFO (the parent `auditoria` is WARNING in production), so these lines are kept in production; 2xx → INFO, 4xx → WARNING, 5xx → ERROR.
- **`POST /api/intenciones`** (`inventario.registrar_intencion_api`): optional `origen` (n8n's conversation id) is stored only as an HMAC, `sesion_id = "api:<hmac>"`; without it, `"api:anon"`. Dedup on same moto + same `sesion_id`: 24 h with `origen`, 10 min without → `200 {"ok": true, "duplicada": true}`, nothing inserted. Caps counted in the database over 24 h: 15 per moto, 200 overall → `429` + WARNING. Intentions with `origen` count in the catalog order as one more person each (`catalogo_ordenado` counts distinct `sesion_id`). The dedup is check-then-insert, not atomic: fine for a single consumer.
- **Rate limits are in memory, per process** (`app/seguridad/limites.py`): counters reset on every deploy/restart and are not shared between gunicorn workers. Known and deliberately not fixed yet (needs a shared store such as Redis). Don't rely on them for a cap that must hold — count in the database, as `/api/intenciones` does.

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

Key design point: **the AI converses, the server decides.** The model never directly executes a save. An independent extractor reads the conversation and reports structured data (a bounded task: read and return JSON); the server then validates and decides whether to persist it. The browser keeps the chat history and resends it on every message, so the history is untrusted input: every assistant reply is HMAC-signed by the server (`app/servicios/historial_chat.py`, keyed on `SECRET_KEY` + the session's `chat_id` + the message type) and any "bot" message without a valid signature is dropped before it reaches the model or the consent check. The conversation is deliberately not stored server-side (that would hold personal data before consent). The consent question is never written by the model: the server emits it with fixed text (`extractor.PREGUNTA_CONSENTIMIENTO`, signed as type `consentimiento`) once the required fields are present. Consent is then verified twice — the pure-Python `extractor.estado_consentimiento` requires the client's *immediate* reply to that signed question to be affirmative with no negation or doubt, and the extractor must independently report `autorizo: true`; a mismatch blocks the save and the question is asked again. `asistente.atender()` runs a whole turn; the `/chat` route only handles the session. There is no calculator: the chat helps the customer find a moto and offers financing (or a cash purchase) for the moto the customer wants and collects contact data — name, WhatsApp and `forma_pago` (`financiado` | `contado` | `por_definir`, required; `contado` is the asesor's priority flag), plus optional email and `moto_interes`. When the chat is opened from a moto's detail page the browser sends that `moto_id`; the server re-checks it (`asistente.moto_en_contexto`) before using it as context or linking the lead to it. Migration 028 (`leads_chat.moto_interes`, `forma_pago`) must be applied before deploying this code. The model has one read-only tool, `buscar_motos` (at most `MAX_BUSQUEDAS` per reply): its parameters are translated to the catalog's URL filters and go through `catalogo.limpiar_filtros` (`catalogo.buscar_para_asistente`), it reads with the public client, and it returns only whitelisted public fields (never the row: the view also carries plate, SOAT, etc.). The motos it finds reach the customer as cards built by the server (`motos` / `url_catalogo` in the `/chat` response), not as model-written links; cards are dropped when the server replaces the model's reply. Real prices from that turn are exempted from the installment detector (`_menciona_cuotas(texto, precios_reales)`). The assistant is prevented from quoting financing installment amounts (a past incident produced plausible-but-wrong numbers); the server scans outgoing replies and strips any quoted figures rather than trusting the prompt alone. The model's context is restricted to public information only (aggregate inventory, locations, hours) — never leads, users, or other customers' data.

### PWA and push reminders

The public site is an installable PWA. `/manifest.json` and `/sw.js` are Flask routes in `app/publico/routes.py` served from the root on purpose (a service worker's scope is the folder it's served from); the SW source lives in `static/pwa/sw.js`. `app/templates/_pwa_head.html` is included only in **public** templates, never in the admin panel. Icons are generated by `scripts/generar_iconos_pwa.py` from `static/logo.png`.

`/recordatorio-soat` lets an anonymous visitor subscribe to SOAT/tecnomecánica expiry reminders (`app/servicios/recordatorios.py`):
- The device gets a secret token (kept in `localStorage`) to edit/delete its reminder now and claim it from an account later. **Only its SHA-256 is stored** (`token_hash`); the plain token leaves the server exactly once, in the POST response.
- The subscription endpoint must be `https` on an allow-listed push service host (`HOSTS_PUSH` in `app/seguridad/suscripcion_push.py`): the server will POST to it when sending, so an arbitrary URL would be an SSRF vector. The subscription is rebuilt field by field, never stored as received.
- Plate + subscription are personal data: consent is mandatory and the policy version is recorded, as with leads.
- Sending: `scripts/enviar_recordatorios.py` (daily job, its own cron). The Web Push call itself (VAPID signing, endpoint re-validation) lives in `app/servicios/push.py`, shared with the motero's alerts; each caller decides what a 404/410 deactivates. The anonymous reminders and the motero's alerts are two separate systems that coexist for now.

Staff push (migration 027, `app/servicios/notificaciones_staff.py`): gerencia, admin and asesores (`ROLES_NOTIFICACIONES`; not `encargado_sede`) subscribe a browser with the "Activar notificaciones" button. Button and script live in one partial, `_notif_staff.html`, included in the sidebar of both `base_gerencia.html` and `base_operativa.html` → `POST /admin/activar-notificaciones` (the old `/admin/gerencia/activar-notificaciones` still works; JSON, CSRF in `X-CSRFToken`). `usuario_id` comes from the session, never the body. It's stored in `dispositivos_staff` (FK `usuarios`, RLS on with no policies, so service_role only), **separate from the motero's `dispositivos`**; upsert on `(usuario_id, endpoint)` reactivates instead of duplicating. The panel doesn't include `_pwa_head.html`, so that script registers `/sw.js` itself. On iOS it only works from the app installed from the public site, with a fresh login inside it. Sending: the only notice so far is `avisar_lead_nuevo()` — when the chat saves a lead, every active device of users who are asesores **at send time** (`repositorios.dispositivos_staff_por_rol` joins `usuarios` on current `rol`/`activo`) gets a push linking to `/admin/leads/<id>`. The payload carries no customer data (it goes through Google/Apple and shows on the lock screen); a cash-purchase lead only changes the title to the priority one. 404/410 → `dispositivos_staff.activo = false`. `asistente.intentar_guardar_lead` fires it in a daemon thread (`avisar_lead_nuevo_en_segundo_plano`) so the customer never waits on push services, and a failure never undoes the save — tests must stub that function (see the autouse fixture in `tests/test_asistente.py`). Any future notice must likewise resolve recipients by current role at send time.

Chat leads inbox (`/admin/leads`, migration 029, `app/servicios/leads_chat.py`, "Leads del chat" in `base_operativa.html`): roles `asesor`, `admin`, `gerencia`. `leads_chat.estado` goes `nuevo → tomado → primer_contacto → segundo_contacto → cita_pendiente → vendido | descartado` (see "Lead follow-up" below); `asesor_id`/`asesor_nombre` (frozen text, like ventas) record who took it. Only an asesor takes a lead and the first one keeps it: `repositorios.tomar_lead_chat` is a single conditional UPDATE (`estado = 'nuevo'` and `asesor_id is null`), never read-then-write. An asesor sees untaken leads plus their own, and **does not see phone/email of an untaken lead** (first name only) until taking it; admin/gerencia see everything, admin can also manage someone else's lead, gerencia is read-only. `forma_pago = 'contado'` is the priority flag: sorted first, highlighted, and used for the push title. Deploy order: migrations 027, 028 and 029 before this code.

Lead follow-up (migration 030, same service and templates): once taken, the lead belongs to that asesor, who moves it through the stages above. `tomado` is shown as "Por contactar"; `ESTADOS_DE_SEGUIMIENTO` are the open stages, `ESTADOS_DE_CIERRE` = `vendido`/`descartado`. Stages are not a forced ladder: skipping, going back and reopening a closed lead are all allowed. The value `contactado` is still accepted by the DB check but no longer written; the code reads it as `primer_contacto` (`ESTADOS_ANTERIORES`). One form on the lead page posts to `/admin/leads/<id>/seguimiento` → `leads_chat.registrar_seguimiento`: optional new state, optional `proximo_contacto` (a date, no time; empty clears it, absent leaves it; only validated when it changes, so an overdue date doesn't block adding a note; closing a lead clears it) and an optional plain-text note (max 1000). The UPDATE is conditioned on the state that was read and on `asesor_id`, so a concurrent change isn't overwritten. `leads_notas` is the lead's timeline, **append-only** (service_role has only SELECT/INSERT): the asesor's notes (`tipo = 'nota'`) plus one automatic row per state/date change (`'evento'`). Notes can hold customer data: never log their text or put it in a push. "Para hoy" = open leads whose `proximo_contacto` is today or earlier; it heads `/admin/leads` and the asesor's Mi espacio. On a validation error the lead page is re-rendered (400) instead of redirecting, so the typed note isn't lost; errors that do travel in the URL (`?error=`) are **codes** looked up in `ERRORES_LEADS`, never free text. Deploy order: migration 030 before this code (it selects `proximo_contacto`). Still to build: leads added by hand from other channels, and the daily push "you have N customers to contact today".

Asesor's "Mi espacio" (`/admin/mi-espacio`, endpoint `admin.espacio_asesor`, `app/servicios/espacio_asesor.py`): the asesor's landing page, role `asesor` only. It shows how many ventas, compras and permutas they made in a week (Monday–Sunday, cut in Colombia time; `?semana=AAAA-MM-DD` picks a past week, never the future), each one's moto, and the available chat leads. **No money values, by decision**: the three `*_de_asesor_en_rango` repository queries don't even select price columns — don't add them. Rows are filtered by `asesor_id` = the session's `usuario_id` (who made the deal, not who registered it); annulled ventas don't count (`estado = 'activa'`, as in the gerencia summary). Where each role lands after login lives in `app/auth/destino.py`: gerencia → metrics, asesor → Mi espacio, others → inventory. A request without a session to `/admin/leads` or `/admin/leads/<id>` (tapping the lead push with the app closed) is remembered in `session["panel_destino"]` and used once after login; the stored path is accepted only if it matches that exact pattern, so it can't become an open redirect. The public manifest has a "Panel del equipo" shortcut to `/admin/`. **The asesor only consults the panel; they register no operation**: no ventas, compras or permutas. `/admin/vender/<id>` is `ROLES_VENTAS` (admin, gerencia, encargado_sede) and always asks which asesor made the sale (`inventario.vender_moto` no longer takes the role; the "Vendida" button on the inventory card is hidden for the asesor). The old asesor-only `/admin/comprar` route, its template and `inventario.comprar_moto` were removed; compras go through `/admin/compras/nueva` (`ROLES_COMPRAS`). In all three the form picks the asesor who gets the credit, which is what Mi espacio lists. On the moto detail the asesor **sees** the RUNT data of motos in their sede (`ROLES_VEN_DATOS_CONTRATO`, only the columns in `contratos.ETIQUETAS_VISIBLES`, so no previous-owner data) but cannot load or replace it (`ROLES_DATOS_CONTRATO`).

### Data model notes

Core tables (see `migraciones/001_esquema_inicial.sql` for the full initial schema): `sedes`, `contactos`, `politicas_privacidad`, `usuarios`, `motos`, `fotos_motos`, `intenciones`, `ventas`, `compras`, `permutas`, `leads_chat`, `conversaciones`, `mensajes`. **`contactos`, `conversaciones` and `mensajes` are unused**: they belonged to the Meta/Twilio webhook and `POST /api/mensajes`, both removed (there is no WhatsApp integration in the code any more). No application code reads or writes them. Their rows were left in place on purpose; dropping them is a separate migration still to be decided. Later migrations add, among others, `datos_contrato` (007), `recordatorios` (019), `perfiles`/`motos_usuario` (021), `dispositivos`/`alertas`/`alertas_avisos` (023) `permutas.asesor_id`/`asesor_nombre` + `registrar_permuta_moto()` (025), `dispositivos_staff` (027), `leads_chat.moto_interes`/`forma_pago` (028) `leads_chat.estado`/`asesor_id`/`asesor_nombre` (029) and `leads_chat.proximo_contacto` + `leads_notas` (030). Number 026 is taken on the unmerged `feat/permuta-contrato` branch.

- Sensitive/financial fields are encrypted with Fernet (`app/seguridad/cifrado.py`); the key (`CLAVE_CIFRADO`) lives only in env vars, never in the database or repo.
- Privacy consent is versioned: `politicas_privacidad` archives each policy version's full text with a SHA-256 hash, and each lead records which version it consented to.
- Sales/purchase records intentionally denormalize: they freeze the moto description and seller name as text at time of transaction (in addition to keeping the original foreign keys), so historical records stay readable even if the moto is deleted or a user is renamed.

### Migrations

SQL migrations live in `migraciones/`, numbered sequentially (`NNN_descripcion.sql`; the old duplicate `005_` pair is now `005a_`/`005b_`). Before adding one, list the folder **including untracked files** — migrations are sometimes created locally before being committed — and take the next free number. Not all schema changes have historically been captured as migrations (some were applied directly against the database), which has caused at least one schema/code drift incident — when changing the schema, always add a migration file rather than applying changes out-of-band.

## Pendientes

- **Rama `docs/claude-md`** (subida al remoto el 2026-11-11 solo como respaldo; un único commit `883e0be` del 2026-10-08 que toca `CLAUDE.md`, 129 commits detrás de `main`): revisar si lo que agrega (tests, migraciones, aislamiento por sede, contratos) ya está cubierto por este archivo. Si lo está, borrar la rama (local y remoto); si no, traer a mano lo que falte y luego borrarla. No fusionarla tal cual: pisaría el `CLAUDE.md` actual.

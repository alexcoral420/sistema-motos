# Universal Motors — Sistema de gestión y catálogo

Sistema en producción para una compraventa de motocicletas usadas en Bogotá.
Gestiona el inventario, atiende al público en un catálogo web, y capta clientes
interesados en financiación mediante un asistente conversacional con IA. Además
ofrece a los clientes un espacio propio ("Mi espacio") con avisos push de
vencimiento de SOAT, tecnomecánica y cuotas de crédito.

**En producción:** [universalmotors.online](https://universalmotors.online)
**Stack:** Python · Flask · PostgreSQL (Supabase + Supabase Auth) · API de Anthropic · Web Push (PWA) · Railway

No es un proyecto de práctica: opera sobre datos reales de un negocio con dos
sedes, más de 120 motos en inventario y varios asesores usándolo a diario.

---

## Índice

- [Qué resuelve](#qué-resuelve)
- [Arquitectura](#arquitectura)
- [Seguridad](#seguridad)
- [Asistente de IA](#asistente-de-ia)
- [Mi espacio del motero](#mi-espacio-del-motero)
- [PWA y notificaciones push](#pwa-y-notificaciones-push)
- [Datos personales y cumplimiento](#datos-personales-y-cumplimiento)
- [SEO y captación](#seo-y-captación)
- [Decisiones deliberadas](#decisiones-deliberadas)
- [Estado y deuda técnica](#estado-y-deuda-técnica)
- [Puesta en marcha](#puesta-en-marcha)

---

## Qué resuelve

Antes del sistema, el inventario vivía en hojas de cálculo y fotos de WhatsApp. No había forma de saber qué motos generaban interés, quién vendía qué, cuánto tiempo permanecía una moto en inventario ni contar con una vitrina digital que pudiera consultarse y filtrarse.

El sistema centraliza la operación y convierte los datos generados diariamente por el negocio en información útil para la operación y la toma de decisiones.

El sistema cubre estos frentes:

| Frente | Qué hace |
|---|---|
| Inventario | Alta, edición, galería de fotos (compresión en el navegador, miniaturas, visor 360), ciclo de publicación (`por_publicar` → publicada) y gestión por sede. Exportación del inventario filtrado a CSV (solo admin). |
| Catálogo público | Vitrina filtrable por marca, cilindraje, año, precio y sede, con filtrado instantáneo por fetch (mejora progresiva). |
| Operaciones | Registro de ventas, compras y permutas con trazabilidad por asesor, verificación por el encargado de sede, generación automática de contratos de compraventa y módulo de gastos (taller + manuales). |
| Captación | Asistente de IA que guía al cliente y registra leads interesados en financiación. Estimador público "¿cuánto vale mi moto?" basado en agregados del inventario. |
| Mi espacio | Cuenta del cliente (motero) con sus motos y alertas push de SOAT, tecnomecánica y cuotas de crédito. |

### Información para la toma de decisiones

A partir de los datos registrados por la operación, el panel de gerencia
ofrece vistas con gráficos (Chart.js) y filtros de fecha, entre ellas:

- Ritmo de ventas y ventas acumuladas.
- Ventas, compras y permutas por asesor.
- Motos más consultadas e interés por marca.
- Interés por rango de precio: tasa de clics por moto, mes a mes.
- Modelos recibidos en permuta.
- Detalle de ventas y compras (solo lectura) y gastos por sede.

Esto permite que la información generada durante la operación diaria no se limite al registro de datos, sino que pueda utilizarse posteriormente para analizar el comportamiento del negocio y apoyar decisiones operativas y comerciales.

## Arquitectura

El sistema sigue una separación estricta de capas. Cada una tiene una sola
responsabilidad y no invade las demás:

```
ruta (blueprint)  →  servicio  →  repositorio  →  Supabase
   orquesta          decide       consulta        almacena
```

**Rutas** (`app/admin`, `app/publico`, `app/api`, `app/auth`, `app/webhook`,
`app/motero`): reciben la
petición, delegan y devuelven la respuesta. No validan ni consultan.

**Servicios** (`app/servicios`): contienen la lógica de negocio y la validación
de entrada. Es donde vive el criterio: qué es un filtro válido, qué datos se le
piden a un cliente, cuándo se guarda un lead.

**Repositorios** (`app/db`): hablan con la base. No conocen vocabulario de
negocio — reciben datos ya validados y traducidos.

Esta separación no es decorativa. Cuando se agregaron los filtros de cilindraje
y año al catálogo, el cambio tocó un solo servicio: las rutas y el repositorio
no se enteraron de que existía un concepto nuevo.

### Blueprints

- `publico` — catálogo, detalle de moto, landing de financiación, chat
- `admin` — panel de gestión (prefijo `/admin`, protegido por rol)
- `auth` — login y sesiones
- `api` — API REST para integraciones externas (autenticada por API key)
- `webhook` — recepción de eventos de mensajería (WhatsApp / Meta)
- `motero` — "Mi espacio" del cliente: `/registro`, `/ingresar`, `/salir`,
  `/mi-espacio`. Las cuentas viven en Supabase Auth, no en `usuarios`.

### Dos clientes de Supabase, distinto privilegio

- `get_supabase_publico()` — clave `anon`, solo lectura, sujeta a RLS. La usa
  el catálogo público, la superficie más expuesta. La RLS de `anon` sobre
  `motos` solo deja ver las motos disponibles.
- `get_supabase_admin()` — `service_role`, salta la RLS. Solo se usa desde
  código detrás del login (el inventario del panel la usa para ver todos los
  estados).
- El motero usa un tercer camino: clave `anon` + su propio JWT, en un cliente
  nuevo por petición. La RLS (`auth.uid()`) es la barrera real.

### Fuentes únicas de verdad

Un patrón recurrente: cuando una decisión se repite en varios lugares, se
centraliza en uno solo.

- `app/servicios/campos_credito.py` — qué datos se le piden al cliente. De ahí
  se generan el prompt del asistente, el esquema del extractor y la validación.
  Agregar un campo es editar una lista.
- `config.WHATSAPP_CONTACTO` — el número de contacto, inyectado en todas las
  plantillas por un context processor.
- `app/servicios/catalogo.py` — los rangos de los filtros, que alimentan a la
  vez la validación, la consulta y las etiquetas de la interfaz.

---

## Seguridad
El proyecto arrancó con una auditoría propia que identificó nueve hallazgos de seguridad, corregidos de forma sistemática antes de continuar con el desarrollo de nuevas funcionalidades.


| Vulnerabilidad | Medida implementada |
|---|---|
| Contraseñas en texto plano | Hash con scrypt (Werkzeug) |
| Sin control de acceso | RBAC con decorador `@requiere_rol` |
| Formularios sin protección | CSRF global con Flask-WTF |
| Entrada sin validar | Lista blanca estricta en servicios |
| Fuerza bruta en login | Rate limiting por IP con Flask-Limiter |
| Sin trazabilidad | Logging de auditoría de acciones sensibles |
| Base expuesta | RLS activo y mínimo privilegio por rol |
| Subida de archivos sin verificar | Validación por magic bytes |
| Identidad manipulable | La identidad sale siempre de la sesión firmada |

### Principios aplicados

**El cliente orienta, el servidor protege.** Los botones ocultos por rol son
comodidad visual, nunca una barrera. Si alguien manipula el HTML y hace
aparecer un enlace al panel, el `before_request` del blueprint admin lo
rechaza igual. La seguridad no depende de lo que se muestre.

**La identidad nunca viene del formulario.** Al registrar una venta o verificar
una operación, el usuario se toma de `session`, no de un campo enviado. Un
asesor no puede registrar una venta a nombre de otro, aunque edite el HTML.

**Mínimo privilegio en la base.** Las tablas sensibles tienen RLS activo,
permisos revocados al rol público, y acceso explícito solo para el backend.
Cada tabla nueva sigue el mismo patrón: activar RLS, revocar a `anon`,
otorgar a `service_role`.

**Excepciones razonadas, no por comodidad.** La ruta del chat está exenta de
CSRF porque no modifica datos del usuario: solo consulta. La misma lógica por
la que la API está exenta. Lo que sí modifica —verificar una venta, por
ejemplo— lleva token. Del mismo modo, `GET /api/avaluo` (solo agregados) y
`POST /api/recordatorios` son públicos y se protegen con rate limit en lugar
de API key: los llama el navegador, y una clave en la página quedaría expuesta.

**Defensa en profundidad.** Los datos financieros sensibles están protegidos
por cuatro capas independientes: RLS impide el acceso, el cifrado los vuelve
ilegibles, la clave vive fuera de la base, y la auditoría registra los accesos.
Cada capa asume que las otras pueden fallar.

---

## Asistente de IA

Un asistente conversacional en el sitio público que orienta al cliente y capta
leads de financiación. Construido sobre la API de Anthropic.

Lo que lo distingue no es que converse, sino **las garantías que el servidor
impone sobre lo que hace**.

### El problema: las acciones no pueden ser probabilísticas

Un modelo de lenguaje decide si ejecutar una herramienta. Esa decisión es
probabilística: a veces la toma, a veces prefiere responder con texto.

Para calcular una cuota, fallar es barato — el cliente vuelve a preguntar.
Para guardar un lead, fallar significa perder un cliente **y mentirle**: el
asistente le dice "un asesor te contactará" y no queda registro de nadie.

Se le dio el mismo mecanismo a dos acciones con consecuencias muy distintas.
Ese fue el error de diseño.

### La solución: la IA conversa, el servidor decide

El guardado dejó de ser una herramienta del modelo. Ahora:

1. La IA mantiene la conversación con el cliente.
2. Un **extractor** independiente lee la charla y reporta qué datos hay (tarea
   acotada, sin criterio: leer y devolver JSON).
3. El **servidor** valida esos datos y decide si guarda.

La salida del modelo se trata como entrada no confiable, igual que un
formulario. Nada de lo que reporte se guarda sin validar.

### Verificación independiente del consentimiento

El extractor puede equivocarse o ser manipulado. Y un falso positivo en el
consentimiento no es un bug: es un incumplimiento del Habeas Data.

Por eso el consentimiento se verifica **dos veces**: el extractor lo reporta, y
una función en Python puro recorre la conversación real buscando que el
asistente haya preguntado y que el cliente haya respondido afirmativamente
después. Si no coinciden, no se guarda.

### Garantía sobre las cifras

El asistente no cotiza cuotas. La cuota real la define la entidad financiera
según el perfil del cliente, y un número que después cambia genera fricción
cuando el asesor retoma el contacto.

El prompt se lo prohíbe, pero el prompt orienta y el código protege: antes de
enviar una respuesta, el servidor detecta si menciona cifras de cuota y, en ese
caso, la reemplaza. Ante la duda, ninguna cifra.

Este control nació de un fallo real: el asistente respondía con cuotas
inventadas que parecían verosímiles (`$729.166` cuando el cálculo correcto era
`$764.484`). Un fallo silencioso que producía salida plausible — más peligroso
que uno que revienta.

### Alcance restringido

El contexto que recibe el modelo contiene **solo información pública**: cifras
agregadas del inventario, ubicaciones, horarios. Nunca leads, nunca usuarios,
nunca datos de otro cliente. Aunque alguien lograra que el asistente revelara
todo su contexto, obtendría información que ya está en el catálogo.

El radio de daño lo define el código disponible, no el prompt: las funciones
que puede invocar son específicas y estrechas. Nunca genéricas.

---

## Mi espacio del motero

Un espacio propio para el cliente final (`app/motero/`): registra sus motos y
recibe alertas de vencimiento en el celular.

### Aislamiento por diseño

El módulo **nunca importa** el cliente `service_role` ni los repositorios del
panel, ni directa ni transitivamente; un test lo verifica en un subproceso
limpio. Todo acceso a datos va con la clave `anon` y el JWT del motero, así que
las consultas no filtran por usuario a mano: lo hace la RLS. Un error en el
código del motero no puede leer datos de otro cliente.

- **Un cliente de Supabase por petición.** supabase-py guarda la sesión dentro
  del cliente; compartirlo haría que un login cambiara el JWT de todas las
  consultas posteriores, incluido el catálogo público.
- **Tokens cifrados en la sesión.** La cookie de Flask está firmada, no
  cifrada; los tokens del motero se guardan cifrados con Fernet y se refrescan
  cuando están por vencer.
- **Sesión compartida, cierre selectivo.** Panel, sitio público y motero
  comparten cookie: cada uno borra solo sus propias claves al cerrar sesión.
- **Consentimiento sellado por la base.** La versión de la política aceptada la
  escribe un trigger al crear la cuenta, y el rol `authenticated` no tiene
  permiso de modificar esas columnas.

### Alertas

Un modelo genérico de alertas con las reglas de cada tipo en una sola tabla
(`TIPOS_ALERTA_FECHA`):

| Tipo | Recurrencia | Avisos |
|---|---|---|
| Cuota de crédito | Mensual | 3 y 1 días antes |
| SOAT | Anual, una por moto | 30, 15, 7 y 1 días antes |
| Tecnomecánica | Anual, una por moto | 30, 15, 7 y 1 días antes |

La fecha registrada es un ancla que **nunca se reescribe**: cada ciclo se
calcula a partir de ella. Correr el ancla mes a mes desplazaría para siempre
una fecha de día 31 o de 29 de febrero.

El envío lo hace un job diario (`scripts/enviar_alertas.py`, con `--dry-run`).
La decisión de qué avisar es una función pura y probada; se deduplica por
alerta, ciclo y umbral, de modo que un aviso no se repite aunque el job corra
dos veces, y si el job falla un día, el siguiente se pone al día.

---

## PWA y notificaciones push

El sitio público es una PWA instalable. El service worker se sirve desde la
raíz porque su alcance es la carpeta desde la que se sirve; el panel de
administración queda fuera de la PWA a propósito.

Además de las alertas de Mi espacio, un visitante anónimo puede suscribirse a
recordatorios de SOAT y tecnomecánica (`/recordatorio-soat`):

- **Token de un solo uso visible.** El dispositivo recibe un token secreto para
  editar o borrar su recordatorio; en la base solo queda su hash SHA-256.
- **Protección contra SSRF.** El servidor hará un POST al endpoint de la
  suscripción, así que solo acepta `https` en una lista blanca de servicios de
  push, y reconstruye la suscripción campo por campo en lugar de guardarla tal
  como llega.
- **Limpieza automática.** Si el servicio de push responde 404/410, el
  dispositivo se desactiva.

El envío Web Push (firma VAPID, revalidación del endpoint) vive en un único
servicio compartido por ambos sistemas.

---

## Datos personales y cumplimiento

El sistema recolecta datos de contacto de personas naturales en Colombia y contempla mecanismos para registrar y mantener la trazabilidad del consentimiento asociado al tratamiento de esos datos

### Consentimiento versionado

Registrar que alguien consintió no alcanza: hay que poder demostrar **a qué**
consintió. Si la política de privacidad cambia, los registros anteriores deben
seguir vinculados al texto que la persona aceptó.

La tabla `politicas_privacidad` archiva cada versión con su texto completo, sus
fechas de vigencia y un **hash SHA-256** que permite probar que no fue alterada
después. Cada lead guarda a qué versión dio su consentimiento.


### Cifrado de datos sensibles

Los campos de naturaleza financiera se guardan cifrados con Fernet (cifrado
simétrico). La clave vive en variables de entorno, **nunca en la base ni en el
repositorio**: si alguien accediera a la base, obtendría texto ilegible.

La separación entre la clave y los datos es la garantía. Ambos en el mismo
lugar equivale a no cifrar.

### Límite deliberado

La infraestructura para recolectar datos crediticios (ingresos, reporte en
centrales, historial) está construida y **desactivada a propósito**. Son datos
regulados por la Ley 1266 de 2008, con obligaciones específicas.

Se activarán solo con asesoría legal previa. Hasta entonces, un booleano en
`campos_credito.py` los mantiene fuera del sistema: no se piden, no se
extraen, no se validan, no se guardan.

Construir la capacidad no es lo mismo que usarla.

---

## SEO y captación

Para un negocio local, la visibilidad en búsquedas puede convertirse en un
canal directo de captación. El sistema incorpora estas capacidades como parte
de la funcionalidad de la plataforma.

- **Títulos y descripciones dinámicos** por motocicleta: marca, modelo, año,
  cilindraje y ubicación, generados a partir del inventario disponible.

- **Sitemap XML dinámico** construido a partir de las motocicletas disponibles.
  Cuando una motocicleta deja de estar disponible, deja de aparecer en el
  sitemap generado.

- **Open Graph** en las páginas de detalle: al compartir una motocicleta por
  WhatsApp u otras plataformas compatibles, el enlace genera una tarjeta con
  información e imagen del vehículo.

- **Atribución por asesor**: enlaces con identificadores que persisten en la
  sesión del cliente, permitiendo relacionar una consulta con el asesor que
  originó el enlace.

- **Registro de intenciones**: cada interacción con "preguntar por esta moto"
  queda registrada y puede utilizarse posteriormente en los reportes de
  operación y análisis comercial.

---

## Decisiones deliberadas

Decisiones tomadas con criterio técnico y de negocio que explican por qué el
sistema está construido de esta manera.

**El simulador orienta, pero no decide.** El sistema nunca aprueba ni rechaza
un crédito ni consulta centrales de riesgo. Esa responsabilidad corresponde a
las entidades financieras aliadas. Asumirla implicaría atribuir a la
compraventa responsabilidades que no corresponden a su función.

**Atribución por identificador, no por número.** Los enlaces de asesor utilizan
el identificador interno del usuario y no su número de teléfono. El
identificador se resuelve contra la base de datos, evitando que un cliente
pueda inyectar arbitrariamente un número de teléfono en la URL y limitando la
referencia a asesores existentes.

**Un solo camino de financiación.** El simulador con formulario web fue
eliminado cuando el asistente conversacional lo reemplazó. Mantener dos
sistemas paralelos que almacenaran información en tablas distintas podía
generar inconsistencias. La ruta anterior quedó como redirección permanente
para no romper enlaces publicados.

**Duplicación deliberada donde importa.** Las funciones de verificación de
ventas y compras son casi idénticas y podrían unificarse mediante una función
genérica que recibiera el nombre de la tabla como parámetro. No se hizo:
permitir que una función genérica determine dinámicamente la tabla sobre la
que opera aumenta el riesgo de escribir donde no corresponde. En este caso,
unas líneas de duplicación controlada son un precio aceptable por reducir ese
riesgo.

**Congelar datos históricos.** Las ventas almacenan la descripción de la
motocicleta y el nombre del vendedor como texto, además de conservar las
referencias originales. Si la motocicleta se elimina o el usuario cambia de
nombre, el registro histórico continúa siendo legible. Es una desnormalización
intencional: se sacrifica pureza del modelo relacional en favor de preservar
el contexto histórico de la operación

---
## Estado y deuda técnica

El sistema está en producción y en uso diario. Estos son sus límites conocidos:

**Cobertura de pruebas parcial.** Existe una suite de pytest (`tests/`) que
cubre la lógica pura de servicios —personas, avalúo, búsqueda y exportación
CSV, recordatorios, alertas y el aislamiento del módulo del motero— y corre en
GitHub Actions en cada push y PR. Las pruebas nunca tocan Supabase: los
repositorios se reemplazan con `monkeypatch`. Rutas, plantillas y flujos
completos todavía se verifican manualmente; es la deuda más significativa.

**Desarrollo y producción separados.** Desarrollo y producción utilizan
proyectos distintos de Supabase. El esquema inicial está documentado en
`migraciones/001_esquema_inicial.sql`, lo que permite que otra persona pueda
levantar una base de datos inicial a partir del repositorio. Lo que falta es
mantener este proceso sincronizado mediante migraciones versionadas en cada
cambio futuro del esquema.

**Historial de migraciones incompleto.** Hoy cada cambio de esquema entra como
migración numerada en `migraciones/` (001 a 024). Pero al principio parte de
la evolución de la base se aplicó directamente, sin quedar en el repositorio.
Eso ya produjo un incidente: código y esquema quedaron desincronizados por un
nombre de columna incorrecto, y el fallo solo se detectó al revisar los logs.
Reconstruir esos cambios faltantes sigue pendiente.

**Dos sistemas de recordatorios.** Los recordatorios anónimos y las alertas de
Mi espacio conviven por ahora. Comparten el envío push, pero tienen tablas y
jobs separados; la idea es que un recordatorio anónimo pueda reclamarse desde
una cuenta y, con el tiempo, unificarlos.

**Backups sin verificar.** Existen los backups automáticos del proveedor,
pero todavía no se ha realizado una restauración de prueba. Un backup que
nunca se ha restaurado es una capacidad disponible, no una garantía de
recuperación.

Estas deudas están documentadas y priorizadas. No se ocultan: reconocerlas
forma parte de entender el estado real del sistema y de definir su evolución.

---

## Puesta en marcha

```bash
git clone https://github.com/alexcoral420/sistema-motos.git
cd sistema-motos

python -m venv venv
source venv/bin/activate      # Windows: .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Variables de entorno requeridas (archivo `.env`, nunca versionado):

```
SECRET_KEY=              # firma de las cookies de sesión
SUPABASE_URL=            # URL del proyecto
SUPABASE_KEY=            # service_role (backend)
SUPABASE_ANON_KEY=       # rol público
ANTHROPIC_API_KEY=       # asistente de IA
CLAVE_CIFRADO=           # clave Fernet para datos sensibles
WHATSAPP_CONTACTO=       # número de contacto público
VAPID_PUBLIC_KEY=        # Web Push (generar una vez)
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=           # mailto:...
```

Más las credenciales de WhatsApp (Twilio / Meta Cloud API); la lista completa
está en `.env.example`.

```bash
python run.py                       # http://127.0.0.1:5000
python scripts/crear_usuario.py     # crear un usuario del panel
python -m pytest tests/             # correr las pruebas
```

Jobs diarios (cada uno con su propio cron):

```bash
python scripts/enviar_recordatorios.py   # recordatorios anónimos
python scripts/enviar_alertas.py         # alertas de Mi espacio (--dry-run, --hoy AAAA-MM-DD)
```

En producción (Railway) la app corre con `gunicorn run:app` según el `Procfile`.

> **Sobre las claves VAPID:** cambiarlas invalida todas las suscripciones push
> existentes.

> **Sobre `CLAVE_CIFRADO`:** si se pierde, los datos cifrados quedan
> irrecuperables. No existe forma de descifrarlos sin ella. Debe respaldarse
> fuera del sistema que protege.

---

## Sobre el proyecto

Desarrollado desde cero por una sola persona, en producción y en uso diario por
un negocio real. Más de 280 commits documentan la evolución: desde el cierre
sistemático de vulnerabilidades y el asistente con IA hasta la PWA y el
espacio del motero con alertas push.

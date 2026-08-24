# Universal Motors — Sistema de gestión y catálogo

Sistema en producción para una compraventa de motocicletas usadas en Bogotá.
Gestiona el inventario, atiende al público en un catálogo web, y capta clientes
interesados en financiación mediante un asistente conversacional con IA.

**En producción:** [universalmotors.online](https://universalmotors.online)
**Stack:** Python · Flask · PostgreSQL (Supabase) · API de Anthropic · Railway

No es un proyecto de práctica: opera sobre datos reales de un negocio con dos
sedes, más de 120 motos en inventario y varios asesores usándolo a diario.

---

## Índice

- [Qué resuelve](#qué-resuelve)
- [Arquitectura](#arquitectura)
- [Seguridad](#seguridad)
- [Asistente de IA](#asistente-de-ia)
- [Datos personales y cumplimiento](#datos-personales-y-cumplimiento)
- [SEO y captación](#seo-y-captación)
- [Decisiones deliberadas](#decisiones-deliberadas)
- [Estado y deuda técnica](#estado-y-deuda-técnica)
- [Puesta en marcha](#puesta-en-marcha)

---

## Qué resuelve

Antes del sistema, el inventario vivía en hojas de cálculo y fotos de WhatsApp.
No había forma de saber qué motos generaban interés, quién vendía qué, ni de
darle al cliente una vitrina que se pudiera filtrar.

El sistema cubre cuatro frentes:

| Frente | Qué hace |
|---|---|
| **Inventario** | Alta, edición, galería de fotos, estados, dos sedes |
| **Catálogo público** | Vitrina filtrable por marca, cilindraje, año y precio |
| **Operaciones** | Registro de ventas, compras y permutas con trazabilidad por asesor |
| **Captación** | Asistente de IA que guía al cliente y registra leads de financiación |

---

## Arquitectura

El sistema sigue una separación estricta de capas. Cada una tiene una sola
responsabilidad y no invade las demás:

```
ruta (blueprint)  →  servicio  →  repositorio  →  Supabase
   orquesta          decide       consulta        almacena
```

**Rutas** (`app/admin`, `app/publico`, `app/api`, `app/auth`): reciben la
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
- `webhook` — recepción de eventos de mensajería

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

El proyecto arrancó con una auditoría propia que identificó nueve
vulnerabilidades, cerradas de forma sistemática antes de agregar
funcionalidades. Los primeros commits del repositorio documentan ese trabajo.

| Vulnerabilidad | Cierre |
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
ejemplo— lleva token.

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

## Datos personales y cumplimiento

El sistema recolecta datos de contacto de personas naturales en Colombia, lo
que lo somete a la Ley 1581 de 2012 (Habeas Data).

### Consentimiento versionado

Registrar que alguien consintió no alcanza: hay que poder demostrar **a qué**
consintió. Si la política de privacidad cambia, los registros anteriores deben
seguir vinculados al texto que la persona aceptó.

La tabla `politicas_privacidad` archiva cada versión con su texto completo, sus
fechas de vigencia y un **hash SHA-256** que permite probar que no fue alterada
después. Cada lead guarda a qué versión dio su consentimiento.

Esto responde a la trazabilidad del consentimiento que el marco regulatorio
colombiano viene exigiendo con creciente rigor (Decreto 0368 de 2026 sobre
finanzas abiertas).

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

Para un negocio local, la visibilidad en búsquedas es un canal de ventas
directo. El sistema lo trata como funcionalidad, no como agregado.

- **Títulos y descripciones dinámicos** por moto: marca, modelo, año,
  cilindraje y ubicación, generados desde el inventario real
- **Sitemap XML** construido desde las motos disponibles — una moto vendida
  desaparece del sitemap en la siguiente petición
- **Open Graph** en el detalle: al compartir un enlace por WhatsApp se muestra
  una tarjeta con foto y precio
- **Atribución por asesor**: enlaces con identificador que persisten en la
  sesión del cliente, para saber qué asesor originó cada consulta
- **Registro de intenciones**: cada clic en "preguntar por esta moto" queda
  registrado, alimentando los reportes de gerencia

---

## Decisiones deliberadas

Decisiones tomadas con criterio, que explican por qué el sistema es como es.

**El simulador orienta pero no decide.** El sistema nunca aprueba ni rechaza un
crédito, ni consulta centrales de riesgo. Esa es función de las entidades
financieras aliadas. Asumirla implicaría responsabilidades legales que no
corresponden a una compraventa.

**Atribución por identificador, no por número.** Los enlaces de asesor llevan
el id del usuario, no su teléfono. El id se traduce contra la base, así que un
cliente no puede inyectar un número arbitrario en la URL: solo puede referir a
asesores que existen.

**Un solo camino de financiación.** El simulador con formulario web fue
eliminado cuando el asistente lo reemplazó. Dos sistemas paralelos guardando
en tablas distintas era una fuente de datos inconsistentes. La ruta antigua
quedó como redirección permanente para no romper enlaces publicados.

**Duplicación deliberada donde importa.** Las funciones de verificación de
ventas y compras son casi idénticas y podrían unificarse pasando el nombre de
la tabla como parámetro. No se hizo: una función genérica que recibe la tabla
desde afuera abre la puerta a escribir donde no corresponde. Veinte líneas
duplicadas son un precio barato por esa garantía.

**Congelar datos históricos.** Las ventas guardan la descripción de la moto y
el nombre del vendedor como texto, además de las referencias. Si la moto se
elimina o el usuario cambia de nombre, el registro histórico sigue siendo
legible. Desnormalización intencional: se sacrifica pureza por robustez.

---

## Estado y deuda técnica

El sistema está en producción y en uso diario. Estos son sus límites conocidos:

**Sin pruebas automatizadas.** Cada cambio se verifica manualmente. Es la deuda
más significativa: a medida que el sistema crece, la probabilidad de romper
algo sin notarlo aumenta.

**Sin entornos separados.** Desarrollo y producción comparten la misma
instancia de base de datos. Cualquier prueba local opera sobre datos reales.
Es el problema que más urge resolver.

**Migraciones sin versionar.** El esquema evolucionó mediante cambios aplicados
directamente sobre la base, sin quedar registrados en el repositorio. Ya
produjo un incidente: código y esquema desincronizados por un nombre de columna
mal escrito, que falló silenciosamente hasta revisar los logs.

**Backups sin verificar.** Existen los automáticos del proveedor, pero nunca se
probó una restauración. Un backup que no se restauró es una promesa, no una
garantía.

Estas deudas están documentadas y priorizadas. No se ocultan: reconocerlas es
parte de entender el sistema.

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
```

```bash
python run.py
```

> **Sobre `CLAVE_CIFRADO`:** si se pierde, los datos cifrados quedan
> irrecuperables. No existe forma de descifrarlos sin ella. Debe respaldarse
> fuera del sistema que protege.

---

## Sobre el proyecto

Desarrollado desde cero por una sola persona, en producción y en uso diario por
un negocio real. Más de 100 commits documentan la evolución: desde el cierre
sistemático de vulnerabilidades hasta la construcción del asistente con IA.

.
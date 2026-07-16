# Universal Motors — Reestructuración segura

Reestructuración de un sistema en producción (bot de WhatsApp con IA + catálogo web +
panel administrativo) aplicando arquitectura por capas y seguridad desde el diseño.

**Stack:** Python · Flask · Supabase (PostgreSQL + Storage) · Claude API · Twilio / WhatsApp Cloud API

---

## El problema

El sistema original funcionaba, pero era un único archivo `app.py` con todo mezclado:
rutas públicas, panel de administración, webhook del bot, login y acceso a datos.
Un diagnóstico de seguridad identificó **11 vulnerabilidades concretas**, entre ellas:
contraseñas en texto plano, un webhook que aceptaba cualquier petición sin verificar
su origen, ausencia de límites de peticiones, y entrada de datos sin validar.

El reto: reconstruirlo con criterios profesionales **sin interrumpir la operación del
negocio**, que dependía del sistema en vivo.

## El enfoque

1. **Diagnóstico** — identificar y documentar cada vulnerabilidad.
2. **Priorización** — ordenar por riesgo real, no por facilidad.
3. **Reconstrucción por fases** — el sistema original sigue en producción mientras la
   versión reforzada se construye y prueba por separado.
4. **Cada cambio, entendido y verificado** — no copiar soluciones, sino comprender el
   porqué de cada decisión.

El historial de commits documenta el proceso: cada uno indica qué vulnerabilidad cierra.

---

## Arquitectura

Separación estricta de responsabilidades. Cada capa conoce solo a la siguiente:

```
ruta (blueprint)  →  servicio  →  repositorio  →  cliente  →  base de datos
   recibe HTTP       lógica de     acceso a       conexión
                     negocio        datos
```

```
├── run.py                  # punto de entrada
├── config.py               # configuración por ambiente (clases + herencia)
│
└── app/
    ├── __init__.py         # application factory: create_app()
    │
    ├── auth/               # autenticación
    │   ├── security.py     #   hashing y verificación de contraseñas
    │   ├── decorators.py   #   control de acceso
    │   └── routes.py       #   /login, /logout
    │
    ├── webhook/            # superficie expuesta a internet
    │   ├── verificacion.py #   validación de firmas HMAC
    │   ├── procesador.py   #   orquestación del flujo del mensaje
    │   └── routes.py       #   endpoint del webhook
    │
    ├── admin/              # panel protegido (blueprint completo)
    ├── publico/            # catálogo y páginas sin datos sensibles
    │
    ├── servicios/          # lógica de negocio (no conoce HTTP → testeable)
    │   ├── inventario.py
    │   └── archivos.py     #   subida validada por magic bytes
    │
    ├── db/                 # acceso a datos
    │   ├── cliente.py      #   conexiones por nivel de privilegio
    │   └── repositorios.py
    │
    └── seguridad/          # transversal
        ├── validadores.py  #   validación de toda entrada externa
        ├── limites.py      #   rate limiting
        └── logging_config.py  # auditoría
```

**Decisiones clave:**

- **Application factory** (`create_app()`) en lugar de una app global: permite elegir
  configuración por ambiente y crear instancias aisladas para tests.
- **Blueprints por superficie** (público / admin / webhook): las zonas quedan separadas
  físicamente, y cada una recibe la protección que le corresponde.
- **Capa de servicios sin dependencias de HTTP**: la lógica de negocio no importa
  `request` ni `session`, por lo que puede probarse de forma aislada.
- **Configuración por clases con herencia**: producción tiene `DEBUG = False` grabado en
  la clase. No depende de que nadie lo recuerde.

---

## Seguridad implementada

| # | Vulnerabilidad | Solución |
|---|---|---|
| 1 | Contraseña en texto plano | Hashing con scrypt (werkzeug) + sal aleatoria |
| 2 | Webhook aceptaba cualquier POST | Verificación de firmas HMAC-SHA256 antes de procesar |
| 3 | Sin límite de intentos ni peticiones | Rate limiting por IP (flask-limiter) |
| 4 | Llave con acceso total a la base | RLS + conexiones separadas por privilegio |
| 5 | `debug=True` posible en producción | Configuración por clases y ambiente |
| 6 | Entrada sin validar | Validadores centralizados con enfoque lista blanca |
| 7 | Archivos validados solo por extensión | Detección de tipo real por magic bytes |
| 9 | Sin trazabilidad de eventos | Logging de auditoría con niveles de gravedad |

### Detalles que importan

**Verificación de firmas (webhook).** El webhook es la superficie más expuesta: cualquiera
en internet puede enviarle un POST. Cada petición trae una firma criptográfica calculada
con un secreto compartido; se recalcula y compara **antes de procesar nada**. Firma
inválida → 403, sin tocar la base de datos ni la API de IA.

La comparación usa `hmac.compare_digest`, que tarda lo mismo coincida o no. Una
comparación normal se detiene en el primer carácter distinto, y ese microtiempo filtrado
permitiría reconstruir la firma byte a byte (*timing attack*).

**Magic bytes.** El nombre de un archivo no prueba nada: cualquiera puede renombrar un
ejecutable a `foto.jpg`. La validación lee los primeros bytes del archivo, donde vive la
firma binaria del formato real (`FF D8 FF` para JPEG, `89 50 4E 47` para PNG), y rechaza
todo lo que no sea una imagen permitida, sin importar cómo se llame.

**Mínimo privilegio.** La aplicación usa dos conexiones a la base de datos: una de bajo
privilegio (solo lectura, sujeta a políticas RLS) para el catálogo público —la superficie
más expuesta— y otra administrativa, reservada a operaciones de escritura ya protegidas
por autenticación. Si la llave pública se filtrara, el daño está acotado por diseño.

**Protección centralizada.** El panel administrativo se protege con un `before_request`
que cubre el blueprint completo, en vez de decorar cada ruta. Cualquier ruta nueva nace
protegida: la seguridad no depende de recordar un decorador.

---

## Principios aplicados

- **Seguridad por diseño, no por memoria** — si una protección depende de que alguien la
  recuerde, tarde o temprano falla. Se convierte en estructura.
- **Fail-closed** — cuando la verificación no puede realizarse (falta un secreto, falta
  una firma), la respuesta es rechazar. Nunca "dejar pasar por si acaso".
- **Nunca confiar en la entrada externa** — todo lo que llega de fuera se valida antes de
  usarse. La validación del navegador es comodidad, no seguridad.
- **No inventar criptografía propia** — se usan librerías probadas (werkzeug, hmac,
  validadores oficiales de los proveedores).
- **No dar pistas al atacante** — mensajes de error genéricos, sin tracebacks en
  producción, errores internos que no se exponen.
- **Defensa en profundidad** — capas independientes: si una falla, las demás protegen.
- **Los secretos viven fuera del código** — variables de entorno, nunca en el repositorio.

---

## Estado

Ocho de las once vulnerabilidades del diagnóstico están cerradas. Pendientes: copias de
seguridad automatizadas, política de retención de datos personales (Ley 1581 de 2012,
Colombia) y validación del historial de credenciales del sistema original.

## Ejecución local

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env           # completar con credenciales propias
python run.py
```

---

*Proyecto en desarrollo activo. El sistema original permanece en producción mientras la
versión reestructurada se construye y verifica por separado.*

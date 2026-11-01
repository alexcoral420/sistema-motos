/*
 * Service Worker de Universal Motors.
 *
 * Se sirve desde /sw.js (ruta en app/publico/routes.py), no desde
 * /static/pwa/sw.js: el scope de un SW es la carpeta desde donde se
 * sirve, y así cubre todo el sitio.
 *
 * No intercepta peticiones (no hay handler de fetch): todo va a la red
 * igual que sin SW.
 *
 * Push (recordatorios de SOAT / tecnomecánica): el servidor enviará un
 * JSON {title, body, url} (Fase 2). Si el payload falta o no es JSON se
 * muestra un aviso genérico: con userVisibleOnly, cada push recibido
 * DEBE mostrar una notificación.
 *
 * Al cambiar este archivo, el navegador detecta la versión nueva en la
 * próxima visita (la ruta lo sirve con Cache-Control: no-cache).
 */

const ICONO = '/static/pwa/icon-192.png';
const TITULO_POR_DEFECTO = 'Universal Motors';
const CUERPO_POR_DEFECTO = 'Tienes un recordatorio pendiente.';

self.addEventListener('install', () => {
    // Activar la versión nueva sin esperar a que se cierren las pestañas
    // que usan la anterior.
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    // Tomar control de las pestañas ya abiertas desde el primer momento.
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
    let datos = {};
    try {
        datos = event.data ? event.data.json() : {};
    } catch {
        datos = {};
    }
    event.waitUntil(self.registration.showNotification(
        datos.title || TITULO_POR_DEFECTO,
        {
            body: datos.body || CUERPO_POR_DEFECTO,
            icon: ICONO,
            badge: ICONO,
            data: { url: datos.url || '/' },
        }
    ));
});

// Solo se abren URLs del propio sitio: el payload viene del servidor,
// pero no hay razón para que una notificación lleve a otro dominio.
function urlSegura(url) {
    try {
        const destino = new URL(url, self.location.origin);
        return destino.origin === self.location.origin ? destino.href : self.location.origin + '/';
    } catch {
        return self.location.origin + '/';
    }
}

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const destino = urlSegura(event.notification.data && event.notification.data.url);
    event.waitUntil((async () => {
        // Si ya hay una pestaña o la app abierta, se reutiliza en vez de
        // abrir otra.
        const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const ventana of ventanas) {
            if (new URL(ventana.url).origin === self.location.origin && 'focus' in ventana) {
                await ventana.focus();
                // navigate() falla en pestañas que este SW no controla;
                // en ese caso se abre una ventana nueva.
                try {
                    if ('navigate' in ventana) await ventana.navigate(destino);
                    return;
                } catch {
                    break;
                }
            }
        }
        await self.clients.openWindow(destino);
    })());
});

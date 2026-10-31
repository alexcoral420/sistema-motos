/*
 * Service Worker de Universal Motors (Fase 0: solo instalabilidad).
 *
 * Se sirve desde /sw.js (ruta en app/publico/routes.py), no desde
 * /static/pwa/sw.js: el scope de un SW es la carpeta desde donde se
 * sirve, y así cubre todo el sitio.
 *
 * Por ahora no intercepta peticiones (no hay handler de fetch): todo va
 * a la red igual que sin SW. La lógica de push llega en la Fase 1.
 *
 * Al cambiar este archivo, el navegador detecta la versión nueva en la
 * próxima visita (la ruta lo sirve con Cache-Control: no-cache).
 */

self.addEventListener('install', () => {
    // Activar la versión nueva sin esperar a que se cierren las pestañas
    // que usan la anterior.
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    // Tomar control de las pestañas ya abiertas desde el primer momento.
    event.waitUntil(self.clients.claim());
});

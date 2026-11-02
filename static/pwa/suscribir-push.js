/*
 * Suscripción Web Push compartida: la usan /recordatorio-soat (anónimo) y
 * /mi-espacio (motero con cuenta). Cada página decide qué mensaje mostrar
 * y a dónde manda la suscripción; aquí solo está lo que es igual en ambas.
 *
 * El Service Worker (/sw.js) lo registra _pwa_head.html; aquí solo se
 * espera a que esté listo.
 *
 * Uso:
 *   const caso = PushUM.diagnostico();   // 'ok' | 'ios-sin-instalar' | 'sin-soporte'
 *   const sus = await PushUM.suscribir(vapidPublica);   // PushSubscription.toJSON()
 *   // lanza Error con .codigo = 'denegado' | 'sin-vapid' | 'ios-sin-instalar' | 'sin-soporte'
 */
(function () {
    'use strict';

    // applicationServerKey espera bytes; la llave viene en base64url.
    function base64urlABytes(texto) {
        const relleno = '='.repeat((4 - texto.length % 4) % 4);
        const b64 = (texto + relleno).replace(/-/g, '+').replace(/_/g, '/');
        const crudo = atob(b64);
        return Uint8Array.from(crudo, c => c.charCodeAt(0));
    }

    // iPadOS se presenta como Mac; se distingue por la pantalla táctil.
    const esIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
                  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const instalada = window.matchMedia('(display-mode: standalone)').matches ||
                      navigator.standalone === true;
    const soportaPush = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

    function error(codigo) {
        const e = new Error(codigo);
        e.codigo = codigo;
        return e;
    }

    function diagnostico() {
        // iOS sin instalar va ANTES del chequeo de soporte: en Safari sin
        // instalar PushManager no existe y diríamos "no soportado".
        if (esIOS && !instalada) return 'ios-sin-instalar';
        if (!soportaPush) return 'sin-soporte';
        return 'ok';
    }

    // 'granted' | 'denied' | 'default', o null si el navegador no tiene Notification.
    function permiso() {
        return 'Notification' in window ? Notification.permission : null;
    }

    // La suscripción que ya tiene este navegador, o null (sin pedir permiso).
    async function suscripcionActual() {
        if (diagnostico() !== 'ok' || permiso() !== 'granted') return null;
        const registro = await navigator.serviceWorker.ready;
        const sus = await registro.pushManager.getSubscription();
        return sus ? sus.toJSON() : null;
    }

    // Pide permiso (si hace falta) y devuelve la suscripción, reutilizando
    // la que ya exista en este navegador.
    async function suscribir(vapidPublica) {
        const caso = diagnostico();
        if (caso !== 'ok') throw error(caso);
        if (!vapidPublica) throw error('sin-vapid');

        const resultado = await Notification.requestPermission();
        if (resultado !== 'granted') throw error('denegado');

        const registro = await navigator.serviceWorker.ready;
        const sus = await registro.pushManager.getSubscription() ||
            await registro.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: base64urlABytes(vapidPublica),
            });
        return sus.toJSON();
    }

    window.PushUM = { diagnostico, permiso, suscripcionActual, suscribir };
})();

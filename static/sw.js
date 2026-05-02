// ═══════════════════════════════════════════════════════════════
// Service Worker — Rodonvergés Associats  v4
// ═══════════════════════════════════════════════════════════════

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));

self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : { title: 'Nou missatge', body: '' };
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: '/static/logo.png',
    tag: 'gestoria-msg',
    requireInteraction: false
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});

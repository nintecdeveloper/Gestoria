// ═══════════════════════════════════════════════════════════════
// Service Worker — Rodonvergés Associats  v3
// ═══════════════════════════════════════════════════════════════

console.log('[SW] v3 carregat');

self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
});

self.addEventListener('push', event => {
  console.log('[SW] push rebut');

  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch (_) {
    d = { title: 'Rodonvergés Associats', body: event.data ? event.data.text() : '' };
  }

  console.log('[SW] payload:', d);

  const title   = d.title || 'Rodonvergés Associats';
  const options = {
    body:               d.body  || '',
    icon:               d.icon  || '/static/icon.png',
    tag:                d.tag   || 'ra-push',
    requireInteraction: false,
    data:               { url: d.url || '/' },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if ('focus' in c) return c.focus();
      }
      return clients.openWindow(url);
    })
  );
});

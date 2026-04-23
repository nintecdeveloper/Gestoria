// ═══════════════════════════════════════════════════════════════
// Service Worker — Rodonvergés Associats
// Gestiona Web Push Notifications i notificationclick
// ═══════════════════════════════════════════════════════════════

self.addEventListener('push', event => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { title: 'Rodonvergés Associats', body: event.data ? event.data.text() : '' };
  }

  const title   = data.title || 'Rodonvergés Associats';
  const options = {
    body:              data.body   || '',
    tag:               data.tag    || 'ra-push',
    icon:              data.icon   || '/static/icon-192.png',
    badge:             data.badge  || '/static/badge-72.png',
    requireInteraction: false,
    data:              { url: data.url || '/' },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) return client.focus();
      }
      if (clientList.length > 0 && 'focus' in clientList[0]) return clientList[0].focus();
      return clients.openWindow(targetUrl);
    })
  );
});

// ═══════════════════════════════════════════════════════════════
// Service Worker — Rodonvergés Associats
// Gestiona Web Push Notifications i notificationclick
// ═══════════════════════════════════════════════════════════════

console.log('[SW] Service Worker carregat, versió 2');

self.addEventListener('install', event => {
  console.log('[SW] install — skipWaiting per activar immediatament');
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  console.log('[SW] activate — clients.claim()');
  event.waitUntil(clients.claim());
});

self.addEventListener('push', event => {
  console.log('[SW] push event rebut', event);

  let data = {};
  try {
    data = event.data ? event.data.json() : {};
    console.log('[SW] push data (json):', data);
  } catch (_) {
    const rawText = event.data ? event.data.text() : '(buit)';
    console.warn('[SW] push data no és JSON, text brut:', rawText);
    data = { title: 'Rodonvergés Associats', body: rawText };
  }

  const title   = data.title || 'Rodonvergés Associats';
  const options = {
    body:               data.body  || '',
    tag:                data.tag   || 'ra-push',
    requireInteraction: false,
    data:               { url: data.url || '/' },
  };

  console.log('[SW] showNotification:', title, options);
  event.waitUntil(
    self.registration.showNotification(title, options)
      .then(() => console.log('[SW] showNotification ✅ OK'))
      .catch(err => console.error('[SW] showNotification ❌', err))
  );
});

self.addEventListener('notificationclick', event => {
  console.log('[SW] notificationclick:', event.notification.tag);
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

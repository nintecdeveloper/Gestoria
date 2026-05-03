self.addEventListener('install', e => e.waitUntil(self.skipWaiting()));
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('push', e => {
  let title = 'Gestoria Rodonvergés';
  let body = 'Nou missatge';
  try {
    const data = e.data.json();
    title = data.title || title;
    body = data.body || body;
  } catch {
    body = e.data ? e.data.text() : body;
  }
  e.waitUntil(self.registration.showNotification(title, {
    body: body,
    icon: '/static/logo.png',
    tag: 'gestoria-msg',
    requireInteraction: false
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});

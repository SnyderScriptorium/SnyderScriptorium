/* Snyder Scriptorium admin service worker: push notifications only.
   No offline caching of admin pages (they are dynamic); this worker exists
   so an installed admin PWA can buzz her phone for orders and messages. */

self.addEventListener('push', function (event) {
  var data = {
    title: 'Snyder Scriptorium',
    body: 'You have a new notification.',
    url: '/admin#tab-inbox',
    tag: 'snyder-admin'
  };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) { /* keep defaults */ }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      icon: '/static/pwa/icon-192.png',
      badge: '/static/pwa/icon-192.png',
      data: { url: data.url || '/admin#tab-inbox' }
    })
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/admin#tab-inbox';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].url.indexOf('/admin') !== -1) {
          list[i].navigate(url);
          return list[i].focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});

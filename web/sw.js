// Service Worker: アプリ一式（Pyodide 含む）をキャッシュしてオフラインで動かす。
// __VERSION__ と __ASSETS__ は scripts/build.py が埋め込む。
const CACHE = 'hanafuda-__VERSION__';
const ASSETS = __ASSETS__;

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request, { ignoreSearch: true }).then(
      (hit) =>
        hit ||
        fetch(event.request).catch(() =>
          event.request.mode === 'navigate' ? caches.match('./index.html') : Response.error(),
        ),
    ),
  );
});

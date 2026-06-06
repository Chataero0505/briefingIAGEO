// Service worker sencillo:
//  - La página (index.html) se pide primero a la red para ver lo último;
//    si no hay conexión, se muestra la última versión guardada.
//  - El resto (iconos, manifest) se sirve de la caché.
const CACHE = "briefing-v1";
const ASSETS = ["./", "index.html", "manifest.json", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.mode === "navigate" || req.url.endsWith("index.html")) {
    e.respondWith(
      fetch(req).then(res => {
        caches.open(CACHE).then(c => c.put("index.html", res.clone()));
        return res;
      }).catch(() => caches.match("index.html"))
    );
  } else {
    e.respondWith(caches.match(req).then(r => r || fetch(req)));
  }
});

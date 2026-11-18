/* StockPulse PWA Service Worker
   策略：壳预缓存 + API stale-while-revalidate（30s 内用缓存，后台更新）
   离线时：导航回退 index.html（壳），API 请求回退缓存 */
const CACHE = 'stockpulse-v1';
const SHELL = [
  '/app/',
  '/app/index.html',
  '/app/manifest.webmanifest',
  '/app/icons/icon-192.png',
  '/app/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // 壳资源 /app/*：缓存优先，网络失败也回退缓存
  if (url.pathname.startsWith('/app/')) {
    e.respondWith(
      caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      }))
    );
    return;
  }

  // API /sp-api/v2/*：stale-while-revalidate（30s 内直接用缓存，后台刷新）
  if (url.pathname.startsWith('/sp-api/')) {
    e.respondWith(
      caches.open(CACHE).then(async (c) => {
        const hit = await c.match(e.request);
        const network = fetch(e.request)
          .then((r) => {
            if (r && r.ok) {
              const copy = r.clone();
              c.put(e.request, copy); // 更新缓存并记录时间
              c.put(e.request.url + '#ts', new Response(String(Date.now())));
            }
            return r;
          })
          .catch(() => null);

        if (hit) {
          const tsRes = await c.match(e.request.url + '#ts');
          const ts = tsRes ? Number(await tsRes.text()) : 0;
          if (Date.now() - ts < 30000) return hit; // 30s 内直接给缓存
          return network.then((r) => r || hit);   // 过期则等网络，失败回退缓存
        }
        return network.then((r) => r || c.match('/app/index.html'));
      })
    );
    return;
  }

  // 其它（/docs 等）：网络优先
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});

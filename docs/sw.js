// 서비스 워커 — 앱처럼 설치되게 하고, 오프라인·느린 망에서 마지막으로 본 화면을 보여 준다.
// ★ 네트워크 우선이다(항상 서버에 재검증). 데이터 JSON 이 매일 바뀌므로 캐시를 먼저 쓰면 낡은 숫자를 보여 준다.
//   네트워크가 실패할 때만 캐시로 떨어진다. 캐시는 이 사이트의 GET 요청만, 최대 한 벌(버전 올리면 옛 캐시 삭제).
const CACHE = 'stock-v1';
const SHELL = ['./', 'index.html', 'market-board.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png'];
const ROOT = new URL('./', self.registration.scope).pathname;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || req.headers.has('range')) return;
  if (url.pathname.startsWith(ROOT + 'paper-trading/')) return;   // 모의투자 화면은 이 워커가 건드리지 않는다
  e.respondWith((async () => {
    try {
      const res = await fetch(req, { cache: 'no-cache' });
      if (res.ok) { const c = await caches.open(CACHE); c.put(req, res.clone()).catch(() => {}); }
      return res;
    } catch (err) {
      const hit = await caches.match(req, { ignoreSearch: true });
      if (hit) return hit;
      if (req.mode === 'navigate' && url.pathname === ROOT) { const idx = await caches.match('index.html'); if (idx) return idx; }
      throw err;
    }
  })());
});

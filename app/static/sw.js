// 홈 화면 설치(PWA)를 위한 최소 서비스워커. 데이터는 캐시하지 않는다(항상 최신 상태).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});

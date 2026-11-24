// 고객용 화면
let ME = null, CAT = null, pollTimer = null;

async function boot() {
  CAT = await api("/api/catalog");
  ME = (await api("/api/me")).user;
  if (ME && ME.role === "admin") { location.href = "/admin"; return; }
  window.onhashchange = route; route();
  $("#logoutBtn").onclick = async () => { await api("/api/logout", { method: "POST" }); ME = null; location.hash = "#login"; route(); };
}

function route() {
  clearInterval(pollTimer);
  const [r, id] = (location.hash.slice(1) || "home").split("/");
  $("#nav").classList.toggle("hidden", !ME);
  $("#logoutBtn").classList.toggle("hidden", !ME);
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === r));
  if (!ME && !["login", "signup"].includes(r)) return viewLogin();
  ({ login: viewLogin, signup: viewSignup, home: viewHome, new: viewNew, order: () => viewOrder(id), guide: viewGuide }[r] || viewHome)();
  window.scrollTo(0, 0);
}

function viewLogin() {
  $("#view").innerHTML = `
  <div class="hero"><div class="logo">BURY RICH ASSET PLUS</div><h1>스마트폰 영상으로<br>홍보 숏폼을 만들어 드립니다</h1>
  <p class="muted">촬영한 영상만 올려 주세요. AI가 분석하고 편집합니다.</p></div>
  <div class="card"><label>이메일</label><input id="em" type="email" autocomplete="email">
  <label>비밀번호</label><input id="pw" type="password" autocomplete="current-password">
  <button class="btn gold block" id="go">로그인</button>
  <a class="btn block" href="#signup">처음이신가요? 회원가입 (무료 체험 1편)</a></div>`;
  $("#go").onclick = async () => {
    try { const r = await api("/api/login", { method: "POST", body: form({ email: $("#em").value, password: $("#pw").value }) });
      if (r.role === "admin") { location.href = "/admin"; return; }
      ME = (await api("/api/me")).user; location.hash = "#home"; route();
    } catch (e) { toast(e.message); }
  };
}

function viewSignup() {
  $("#view").innerHTML = `<h1>회원가입</h1><div class="card">
  <label>이름</label><input id="nm"><label>휴대폰 번호</label><input id="ph" type="tel" inputmode="tel">
  <label>이메일</label><input id="em" type="email"><label>비밀번호 <span class="opt">(8자 이상)</span></label><input id="pw" type="password">
  <p class="muted small">입력하신 정보와 영상은 영상 제작 목적으로만 사용되며 외부에 공개되지 않습니다. 고객 영상은 AI 학습에 사용하지 않습니다.</p>
  <button class="btn gold block" id="go">가입하고 시작하기</button><a class="btn block" href="#login">로그인으로</a></div>`;
  $("#go").onclick = async () => {
    try { await api("/api/signup", { method: "POST", body: form({ name: $("#nm").value, phone: $("#ph").value, email: $("#em").value, password: $("#pw").value }) });
      ME = (await api("/api/me")).user; location.hash = "#new"; route();
    } catch (e) { toast(e.message); }
  };
}

async function viewHome() {
  $("#view").innerHTML = `<h1>내 영상</h1><a class="btn gold block" href="#new">➕ 새 홍보 영상 만들기</a><div id="list" class="muted" style="margin-top:12px">불러오는 중…</div>`;
  const orders = await api("/api/orders");
  $("#list").innerHTML = orders.length ? orders.map((o) => {
    const r = o.renders[0];
    const prog = o.job && ["queued", "running"].includes(o.job.status) ? `<div class="progress"><i style="width:${o.job.progress}%"></i></div><div class="small muted">${esc(o.job.step || "대기 중")}</div>` : "";
    return `<div class="list-item" onclick="location.hash='#order/${o.id}'">
      ${r ? `<img class="thumb" src="/files/render/${r.id}.jpg" alt="">` : `<div class="thumb"></div>`}
      <div class="grow"><div class="title">${esc(o.biz_name)}</div>
      <div class="small muted">주문 #${o.id} · ${o.duration}초 · ${esc(CAT.styles[o.style] || "")}</div>
      ${statusChip(o.status)}${prog}</div></div>`;
  }).join("") : `<div class="card muted">아직 요청한 영상이 없습니다. 위 버튼을 눌러 시작해 보세요.</div>`;
  if (orders.some((o) => ["received", "processing"].includes(o.status))) pollTimer = setInterval(() => location.hash === "#home" && viewHome(), 6000);
}

function viewNew() {
  const last = store.get("lastBiz", {});
  const prods = CAT.products.filter((p) => p.period !== "quote");
  const firstAvail = ME.free_trial_used ? prods.find((p) => p.code !== "free_trial") : prods[0];
  $("#view").innerHTML = `<h1>홍보 영상 제작 요청</h1>
  <h2>1. 사업장 정보</h2><div class="card">
    <label>상호명 *</label><input id="biz_name" value="${esc(last.biz_name || "")}">
    <label>업종 *</label><div class="chips" id="industry"></div>
    <label>사업장 주소</label><input id="address" value="${esc(last.address || "")}" placeholder="예) 서울 마포구 망원동 123-4">
    <label>전화번호</label><input id="biz_phone" type="tel" value="${esc(last.biz_phone || "")}">
    <label>홈페이지/SNS <span class="opt">(선택)</span></label><input id="website" value="${esc(last.website || "")}">
    <label>주요 상품·서비스 <span class="opt">(쉼표로 구분)</span></label><div class="mic"><textarea id="products" placeholder="예) 수제 돈까스, 치즈 돈까스, 우동">${esc(last.products || "")}</textarea></div>
  </div>
  <h2>2. 어떤 영상을 원하세요?</h2><div class="card">
    <label>홍보 목적</label><div class="chips" id="purpose"></div>
    <label>주요 고객 연령대</label><div class="chips" id="target_age"></div>
    <label>원하는 분위기</label><div class="chips" id="mood"></div>
    <label>편집 스타일</label><div class="chips" id="style"></div>
    <label>영상 길이</label><div class="chips" id="duration"></div>
    <label>꼭 넣고 싶은 문구 <span class="opt">(가격·행사 등은 여기에 적어 주신 내용만 사용합니다)</span></label>
    <div class="mic"><textarea id="highlights" placeholder="예) 매일 아침 직접 만드는 돈까스, 평일 점심 11시 오픈"></textarea></div>
    <label>참고하고 싶은 인기 숏폼 링크 <span class="opt">(선택)</span></label><textarea id="reference_links" placeholder="유튜브 쇼츠·릴스·틱톡 링크"></textarea>
    <label>기타 요청사항 <span class="opt">(선택)</span></label><div class="mic"><textarea id="request_note"></textarea></div>
  </div>
  <h2>3. 영상·사진 올리기</h2><div class="card">
    <label>촬영한 영상·사진 * <span class="opt">(여러 개 선택 가능)</span></label>
    <input id="files" type="file" multiple accept="video/*,image/*">
    <div id="fileinfo" class="small muted"></div>
    <label>로고 이미지 <span class="opt">(선택)</span></label><input id="logo" type="file" accept="image/*">
  </div>
  <h2>4. 상품 선택</h2><div class="card"><div class="chips" id="product_code"></div>
    <p class="muted small">결제는 영상 확인 후 안내드립니다(카드 결제 연동 준비 중). 조회수·매출 증가는 보장하지 않습니다.</p></div>
  <div id="upbox" class="card hidden"><b>업로드 중…</b><div class="progress"><i id="upbar"></i></div><div id="uptext" class="small muted"></div>
    <p class="small muted">업로드가 끝날 때까지 이 화면을 유지해 주세요. 업로드 후에는 화면을 꺼도 서버에서 계속 제작됩니다.</p></div>
  <button class="btn gold block" id="submit">영상 제작 요청하기</button>`;
  chips($("#industry"), CAT.industries, { value: last.industry || "" });
  chips($("#purpose"), CAT.purposes, { value: "visit" });
  chips($("#target_age"), CAT.ages, { multi: true });
  chips($("#mood"), CAT.moods, { value: "bright" });
  chips($("#style"), CAT.styles, { value: "trend" });
  chips($("#duration"), Object.fromEntries(CAT.durations.map((d) => [String(d), d + "초"])), { value: "30" });
  chips($("#product_code"), Object.fromEntries(prods.filter((p) => !(ME.free_trial_used && p.code === "free_trial")).map((p) => [p.code, `${p.name} · ${p.price ? won(p.price) : "무료"}`])), { value: firstAvail ? firstAvail.code : "" });
  enableVoice();
  $("#files").onchange = () => {
    const fs = [...$("#files").files]; const mb = fs.reduce((a, f) => a + f.size, 0) / 1e6;
    $("#fileinfo").textContent = fs.length ? `${fs.length}개 선택 · ${mb.toFixed(0)}MB${mb > 300 ? " (용량이 커서 와이파이 사용을 권장합니다)" : ""}` : "";
  };
  $("#submit").onclick = submitOrder;
}

async function submitOrder() {
  const v = (id) => ($("#" + id).dataset.value ?? $("#" + id).value ?? "").trim();
  const data = { biz_name: v("biz_name"), industry: v("industry"), address: v("address"), biz_phone: v("biz_phone"), website: v("website"),
    products: v("products"), purpose: v("purpose"), target_age: v("target_age"), mood: v("mood"), style: v("style"), duration: v("duration"),
    highlights: v("highlights"), reference_links: v("reference_links"), request_note: v("request_note"), product_code: v("product_code") };
  if (!data.biz_name) return toast("상호명을 입력해 주세요");
  if (!data.industry) return toast("업종을 선택해 주세요");
  const files = [...$("#files").files];
  if (!files.length) return toast("영상 또는 사진을 선택해 주세요");
  store.set("lastBiz", data);
  const fd = form(data);
  files.forEach((f) => fd.append("files", f));
  if ($("#logo").files[0]) fd.append("logo", $("#logo").files[0]);
  $("#submit").disabled = true; $("#upbox").classList.remove("hidden");
  try {
    const r = await upload("/api/orders", fd, (p) => { $("#upbar").style.width = p + "%"; $("#uptext").textContent = p < 100 ? `${p}%` : "서버 저장 중…"; });
    toast("접수되었습니다! 제작이 시작됩니다.");
    location.hash = `#order/${r.order_id}`;
  } catch (e) { toast(e.message, 5000); $("#submit").disabled = false; $("#upbox").classList.add("hidden"); }
}

const SNS_LABEL = { youtube_title: "유튜브 쇼츠 제목", youtube_description: "유튜브 설명", instagram: "인스타그램 릴스", tiktok: "틱톡",
  naver_blog: "네이버 블로그", naver_place: "네이버 플레이스", threads: "스레드", kakao: "카카오톡", hashtags: "해시태그", local_keywords: "지역 검색 키워드" };

function snsHtml(sns) {
  return Object.entries(SNS_LABEL).filter(([k]) => sns[k]).map(([k, label]) =>
    `<details><summary>${label}</summary><div class="copybox">${esc(sns[k])}</div><button class="btn sm" onclick='copyText(${JSON.stringify(sns[k]).replace(/'/g, "&#39;")})'>복사</button></details>`).join("")
    + (sns.notice ? `<p class="muted small">${esc(sns.notice)}</p>` : "");
}

async function viewOrder(id) {
  const o = await api(`/api/orders/${id}`);
  const busy = ["received", "processing"].includes(o.status) || (o.job && ["queued", "running"].includes(o.job.status));
  const r = o.renders[0];
  const guidance = o.media.flatMap((m) => (m.overall && m.overall.guidance) || []);
  $("#view").innerHTML = `<h1>${esc(o.business.name)}</h1>
  <div>${statusChip(o.status)} <span class="muted small">주문 #${o.id} · ${o.duration}초</span></div>
  ${busy ? `<div class="card"><b>AI가 영상을 만들고 있습니다</b><div class="progress"><i style="width:${o.job ? o.job.progress : 2}%"></i></div>
    <div class="small muted">${esc((o.job && o.job.step) || "작업 대기 중")} · 화면을 꺼도 계속 진행됩니다</div></div>` : ""}
  ${o.status === "review" ? `<div class="card">영상이 완성되어 담당자가 검수 중입니다. 검수가 끝나면 이곳에서 바로 볼 수 있습니다.</div>` : ""}
  ${r ? `<h2>완성 영상</h2><video src="/files/render/${r.id}.mp4" controls playsinline preload="metadata" poster="/files/render/${r.id}.jpg"></video>
    <a class="btn gold block" href="/files/render/${r.id}.mp4?download=1">📥 휴대폰에 저장하기</a>
    <h2>SNS 게시 문구</h2>${snsHtml(r.sns)}` : ""}
  ${guidance.length ? `<h2>다음 촬영 팁</h2><div class="warn">${[...new Set(guidance)].map((g) => "• " + esc(g)).join("<br>")}</div>` : ""}
  ${r ? `<h2>수정 요청</h2><div class="card"><div class="mic"><textarea id="rev" placeholder="예) 자막을 더 크게 해 주세요 / 첫 장면을 음식 장면으로 바꿔 주세요"></textarea></div>
    <button class="btn block" id="revBtn">수정 요청 보내기</button></div>
    <h2>평가</h2><div class="card"><div class="stars" id="stars">${[1, 2, 3, 4, 5].map((i) => `<span data-v="${i}" class="${o.rating >= i ? "on" : ""}">★</span>`).join("")}</div>
    <textarea id="fb" placeholder="의견을 남겨 주세요">${esc(o.feedback || "")}</textarea><button class="btn block" id="rateBtn">평가 저장</button></div>` : ""}
  ${o.revisions.length ? `<h2>요청 내역</h2>${o.revisions.map((v) => `<div class="card small">${esc(v.message)}<div class="muted">${v.status === "open" ? "처리 중" : "반영 완료"}</div></div>`).join("")}` : ""}
  <details><summary>원본 영상 관리</summary><p class="small muted">올리신 원본 ${o.media.length}개 ${o.media.every((m) => m.deleted) ? "(삭제됨)" : ""}. 삭제를 원하시면 아래 버튼을 눌러 주세요. 완성 영상은 유지됩니다.</p>
    <button class="btn red sm" id="delSrc">원본 영상 삭제 요청</button></details>`;
  enableVoice();
  let rating = o.rating || 0;
  if ($("#stars")) $("#stars").onclick = (e) => { const v = +e.target.dataset.v; if (!v) return; rating = v; $$("#stars span").forEach((s) => s.classList.toggle("on", +s.dataset.v <= v)); };
  if ($("#rateBtn")) $("#rateBtn").onclick = async () => { if (!rating) return toast("별점을 선택해 주세요"); await api(`/api/orders/${id}/rating`, { method: "POST", body: form({ rating, feedback: $("#fb").value }) }); toast("감사합니다!"); };
  if ($("#revBtn")) $("#revBtn").onclick = async () => { try { await api(`/api/orders/${id}/revision`, { method: "POST", body: form({ message: $("#rev").value }) }); toast("수정 요청을 보냈습니다"); viewOrder(id); } catch (e) { toast(e.message); } };
  $("#delSrc").onclick = async () => { if (!confirm("원본 영상을 삭제할까요? 되돌릴 수 없습니다.")) return; await api(`/api/orders/${id}/delete-sources`, { method: "POST" }); toast("삭제했습니다"); viewOrder(id); };
  if (busy) pollTimer = setInterval(() => location.hash === `#order/${id}` && viewOrder(id), 5000);
}

function viewGuide() {
  $("#view").innerHTML = `<h1>촬영 안내</h1>
  <div class="card"><h3>📱 기본</h3>• 스마트폰을 <b>세로</b>로 들고 촬영해 주세요<br>• 렌즈를 한 번 닦아 주세요<br>• 화면에서 주인공(상품)을 눌러 초점을 맞춰 주세요</div>
  <div class="card"><h3>🎬 꼭 찍어 주세요 (각 5~10초)</h3>1. 가게 간판·외관<br>2. 매장 내부 전체<br>3. 대표 상품 클로즈업 (천천히 다가가며)<br>4. 만드는 과정 / 서비스하는 모습<br>5. 손님이 즐기는 모습 (동의를 받은 경우만)</div>
  <div class="card"><h3>💡 더 좋게</h3>• 밝은 곳에서, 조명을 켜고 촬영<br>• 두 손으로 잡고 천천히 움직이기<br>• 한 장면에서 3초 이상 멈춰 있기<br>• 음식은 김이 날 때, 위에서·옆에서 모두</div>
  <div class="card muted small">다른 사람의 얼굴이 나오는 경우 반드시 동의를 받아 주세요. 저작권이 있는 음악이 흐르는 상태의 촬영은 피해 주세요.</div>`;
}

boot().catch((e) => { $("#view").innerHTML = `<div class="card">서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.<br><span class="muted small">${esc(e.message)}</span></div>`; });

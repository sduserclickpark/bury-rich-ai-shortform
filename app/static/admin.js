// 운영자(관리자) 화면 — 스마트폰 한 대로 모든 업무 처리
let ME = null, CAT = null, pollTimer = null;
const V = () => $("#view");

async function boot() {
  CAT = await api("/api/catalog");
  ME = (await api("/api/me")).user;
  window.onhashchange = route; route();
  $("#logoutBtn").onclick = async () => { await api("/api/logout", { method: "POST" }); location.href = "/"; };
}

function route() {
  clearInterval(pollTimer);
  if (!ME || ME.role !== "admin") { location.href = "/"; return; }
  $("#nav").classList.remove("hidden"); $("#logoutBtn").classList.remove("hidden");
  const [r, id] = (location.hash.slice(1) || "home").split("/");
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === r || (r === "order" && a.dataset.r === "orders")));
  const views = { home: viewHome, orders: () => viewOrders(id || ""), order: () => viewOrder(id), neworder: viewNewOrder, refs: viewRefs,
    jobs: viewJobs, more: viewMore, products: viewProducts, settings: viewSettings, music: viewMusic, customers: viewCustomers,
    payments: viewPayments, system: viewSystem };
  (views[r] || viewHome)().catch((e) => toast(e.message));
  window.scrollTo(0, 0);
}

// ---------------- 현황 ----------------
async function viewHome() {
  const d = await api("/api/admin/dashboard");
  const o = d.orders, j = d.jobs;
  const k = (v, label, href) => `<div class="kpi" onclick="location.hash='${href}'"><div class="v">${v}</div><div class="k">${label}</div></div>`;
  V().innerHTML = `<h1>오늘의 현황</h1>
  <a class="btn gold block" href="#neworder">➕ 고객 영상 대신 접수하기</a>
  <h2>처리할 일</h2><div class="kpis">
    ${k(o.review || 0, "검수 대기", "#orders/review")}${k(o.revision || 0, "수정 요청", "#orders/revision")}
    ${k((o.received || 0) + (o.processing || 0), "접수·제작 중", "#orders/processing")}${k(j.failed || 0, "실패한 작업", "#jobs")}
    ${k(j.awaiting_approval || 0, "비용 승인 필요", "#jobs")}${k(d.references_pending, "검토할 참고 링크", "#refs")}
  </div>
  <h2>이번 달</h2><div class="kpis">
    ${k(won(d.month_revenue), "매출(입금 확인 기준)", "#payments")}${k(won(d.month_cost_krw), "제작 원가(추정 포함)", "#customers")}
    ${k(d.month_renders + "편", "제작한 영상", "#orders")}${k(won(d.month_ai_krw), "AI 사용료(실측)", "#settings")}
    ${k(d.customers + "명", "고객", "#customers")}${k(d.references + "개", "벤치마킹 자료", "#refs")}
  </div>`;
}

// ---------------- 주문 ----------------
async function viewOrders(status) {
  const rows = await api("/api/admin/orders" + (status ? `?status=${status}` : ""));
  const tabs = { "": "전체", received: "접수", processing: "제작 중", review: "검수 대기", revision: "수정 요청", delivered: "완성", failed: "실패" };
  V().innerHTML = `<h1>주문 관리</h1><div class="chips" id="st"></div><div id="list"></div>`;
  chips($("#st"), tabs, { value: status });
  $("#st").addEventListener("click", () => (location.hash = "#orders/" + $("#st").dataset.value));
  $("#list").innerHTML = rows.length ? rows.map((o) => `<div class="list-item" onclick="location.hash='#order/${o.id}'"><div class="grow">
    <div class="title">#${o.id} ${esc(o.biz_name)}</div>
    <div class="small muted">${esc(CAT.industries[o.industry] || "")} · ${esc(o.customer_name || o.email)} · ${o.duration}초 · ${esc(CAT.styles[o.style] || o.style)}</div>
    ${statusChip(o.status)} ${o.paid ? '<span class="status s-done">입금</span>' : ""} <span class="small muted">영상 ${o.render_count}개</span>
    ${o.job && ["queued", "running"].includes(o.job.status) ? `<div class="progress"><i style="width:${o.job.progress}%"></i></div><div class="small muted">${esc(o.job.step)}</div>` : ""}
  </div></div>`).join("") : `<div class="card muted">해당 주문이 없습니다.</div>`;
  if (rows.some((o) => o.job && ["queued", "running"].includes(o.job.status))) pollTimer = setInterval(() => viewOrders(status), 6000);
}

const STYLE_OPTS = () => Object.entries(CAT.styles).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
const DUR_OPTS = (sel) => CAT.durations.map((d) => `<option value="${d}"${d == sel ? " selected" : ""}>${d}초</option>`).join("");

async function viewOrder(id) {
  const o = await api(`/api/admin/orders/${id}`);
  const b = o.business, busy = o.job && ["queued", "running"].includes(o.job.status);
  V().innerHTML = `<h1>#${o.id} ${esc(b.name)}</h1>
  <div>${statusChip(o.status)} ${o.paid ? '<span class="status s-done">입금 확인</span>' : '<span class="status">미입금</span>'}</div>
  ${busy ? `<div class="card"><b>제작 중</b><div class="progress"><i style="width:${o.job.progress}%"></i></div><div class="small muted">${esc(o.job.step)}</div></div>` : ""}
  ${o.job && o.job.status === "failed" ? `<div class="warn">마지막 작업 실패: ${esc(o.job.error)}<br><button class="btn sm" onclick="retryJob(${o.job.id})">다시 실행</button></div>` : ""}
  ${o.job && o.job.status === "awaiting_approval" ? `<div class="warn">비용 한도 초과 예상: ${esc(o.job.error)}<br><button class="btn sm" onclick="retryJob(${o.job.id})">승인하고 실행</button></div>` : ""}
  ${o.revisions.filter((r) => r.status === "open").map((r) => `<div class="warn"><b>고객 수정 요청</b><br>${esc(r.message)}</div>`).join("")}

  <h2>완성 영상 (${o.renders.length})</h2>
  ${o.renders.map((r) => renderCard(r)).join("") || '<div class="card muted">아직 없습니다.</div>'}

  <h2>영상 제작</h2><div class="card">
    <div class="row"><div><label>스타일</label><select id="pStyle">${STYLE_OPTS()}</select></div>
    <div><label>길이</label><select id="pDur">${DUR_OPTS(o.duration)}</select></div></div>
    <label>첫 3초 후킹 문구 <span class="opt">(비우면 자동)</span></label><div class="mic"><input id="pHook"></div>
    <button class="btn gold block" id="prodBtn">이 설정으로 제작</button>
    <button class="btn block" id="prod3Btn">서로 다른 3가지 스타일로 제작</button>
  </div>

  <h2>원본 분석</h2>
  ${o.media.map((m) => `<details><summary>${m.kind === "video" ? "🎥" : "🖼️"} ${esc(m.original_name)} ${m.overall ? `· 품질 ${m.overall.quality_score ?? "-"}점` : "· 분석 전"}</summary>
    ${m.deleted ? '<p class="muted">원본 삭제됨</p>' : `<a class="small" href="/files/media/${m.id}" target="_blank">원본 보기</a>`}
    ${m.overall ? `<table>${Object.entries({ duration: "길이(초)", resolution: "해상도", orientation: "방향", avg_brightness: "밝기(0~255)", avg_shake: "흔들림", segments: "구간 수", usable_segments: "사용 가능 구간", duplicates: "중복 구간", has_audio: "소리", sound_ratio: "소리 비율" })
      .filter(([k2]) => m.overall[k2] !== undefined).map(([k2, l]) => `<tr><td>${l}</td><td>${esc(m.overall[k2])}</td></tr>`).join("")}</table>
      ${(m.overall.guidance || []).length ? `<div class="warn small">${m.overall.guidance.map(esc).join("<br>")}</div>` : ""}
      ${m.segments ? `<p class="small muted">구간: ${m.segments.map((s) => `${s.start}~${s.end}초 ${s.usable ? (s.duplicate_of !== undefined && s.duplicate_of !== null ? "중복" : "✔") : "✖ " + s.issues.join("/")}`).join(" · ")}</p>` : ""}
      <p class="small">음성 인식: ${m.transcript ? (m.transcript.available ? esc(m.transcript.segments.map((s) => s.text).join(" ") || "(말소리 없음)") : esc(m.transcript.error || "미실행")) : "미실행"}</p>
      <p class="small muted">장면 내용(음식/인물 등) 인식: ${"Claude API 설정 시 제작 단계에서 수행"}</p>` : ""}
  </details>`).join("")}

  <h2>고객·사업장</h2><div class="card small">
    <b>${esc(o.customer.name)}</b> · ${esc(o.customer.phone)} · ${esc(o.customer.email)}<br>
    업종: ${esc(CAT.industries[b.industry])}<br>주소: ${esc(b.address)}<br>전화: ${esc(b.phone)} · ${esc(b.website)}<br>
    상품: ${esc(b.products)}<br>목적: ${esc(CAT.purposes[o.purpose] || "")} · 연령: ${esc(o.target_age)} · 분위기: ${esc(CAT.moods[o.mood] || "")}<br>
    강조 문구: ${esc(o.highlights)}<br>참고 링크: ${esc(o.reference_links)}<br>요청: ${esc(o.request_note)}
    ${o.rating ? `<br>고객 평가: ${"★".repeat(o.rating)} ${esc(o.feedback)}` : ""}
  </div>
  <h2>결제</h2><div class="card">
    ${o.payments.map((p) => `<div class="small">${won(p.amount)} · ${esc(p.method)} · ${esc(p.memo)} · ${p.created_at.slice(0, 10)}</div>`).join("") || '<div class="small muted">입금 기록 없음</div>'}
    <div class="row"><div><label>금액</label><input id="payAmt" type="number" inputmode="numeric" value="${o.price}"></div><div><label>메모</label><input id="payMemo" placeholder="예) 계좌이체 확인"></div></div>
    <button class="btn block" id="payBtn">입금 확인 기록</button>
  </div>
  <h2>상태 변경</h2><div class="card"><select id="stSel">${Object.entries({ received: "접수", processing: "제작 중", review: "검수 대기", delivered: "완성(전달)", revision: "수정 요청", failed: "실패", canceled: "취소" }).map(([k2, v]) => `<option value="${k2}"${k2 === o.status ? " selected" : ""}>${v}</option>`).join("")}</select>
    <button class="btn block" id="stBtn">상태 저장</button></div>`;
  $("#pStyle").value = o.style in CAT.styles ? o.style : "trend";
  enableVoice();
  $("#prodBtn").onclick = () => produce(id, 1);
  $("#prod3Btn").onclick = () => produce(id, 3);
  $("#payBtn").onclick = async () => { await api("/api/admin/payments", { method: "POST", body: form({ order_id: id, amount: $("#payAmt").value, memo: $("#payMemo").value }) }); toast("기록했습니다"); viewOrder(id); };
  $("#stBtn").onclick = async () => { await api(`/api/admin/orders/${id}/status`, { method: "POST", body: form({ status: $("#stSel").value }) }); toast("저장했습니다"); viewOrder(id); };
  if (busy) pollTimer = setInterval(() => location.hash === `#order/${id}` && viewOrder(id), 5000);
}

function renderCard(r) {
  const p = r.plan, c = r.cost || {};
  const caps = p.scenes.slice(1).map((s, i) => `<input class="capIn" data-i="${i}" value="${esc(s.caption || "")}" placeholder="장면 ${i + 2} 자막">`).join("");
  return `<div class="card" id="r${r.id}">
    <div><b>v${r.version}</b> · ${esc(p.style_name)} · ${p.duration}초 ${r.approved ? '<span class="status s-delivered">고객 전달됨</span>' : ""}</div>
    <video src="/files/render/${r.id}.mp4" controls playsinline preload="metadata" poster="/files/render/${r.id}.jpg" style="margin-top:10px"></video>
    <div class="row"><a class="btn sm" href="/files/render/${r.id}.mp4?download=1">📥 저장</a>
      ${r.approved ? "" : `<button class="btn gold sm" onclick="approve(${r.id})">✔ 승인·고객 전달</button>`}</div>
    <details><summary>기획 내용</summary><div class="small">
      <b>제목</b> ${esc(p.title)}<br><b>콘셉트</b> ${esc(p.concept)}<br><b>구성</b> ${esc(p.story)}<br>
      <b>문구 엔진</b> ${p.copy_engine === "claude" ? "Claude AI" : "기본 규칙(무료)"}<br>
      <b>배경음악</b> ${p.music ? esc(p.music.title + " — " + p.music.license) : "없음(원본 소리 사용)"}<br>
      <b>벤치마킹</b> ${p.benchmark && p.benchmark.count ? `참고 ${p.benchmark.count}개 (${p.benchmark.scope === "industry" ? "같은 업종" : "전체 업종"}) 평균 컷 ${p.benchmark.avg_cut_sec ?? "-"}초` : "등록된 참고 자료 없음(스타일 기본값)"}<br>
      <b>내레이션 대본</b> ${esc(p.narration)}<br>${(p.notes || []).map((n) => "• " + esc(n)).join("<br>")}
      <br><b>장면</b> ${p.scenes.map((s, i) => `${i + 1}) ${s.dur.toFixed(1)}초${s.speed !== 1 ? ` ×${s.speed}` : ""}`).join(" · ")}
    </div></details>
    <details><summary>✏️ 문구·자막 수정 후 다시 만들기</summary>
      <label>첫 3초 후킹 문구</label><div class="mic"><input class="hookIn" value="${esc(p.hook_text)}"></div>
      <label>장면별 자막</label>${caps}
      <label>마지막 행동 유도 문구</label><input class="ctaIn" value="${esc(p.cta_text)}">
      <label>엔딩 주소</label><input class="addrIn" value="${esc(p.end_card.address)}">
      <label>엔딩 전화</label><input class="phoneIn" value="${esc(p.end_card.phone)}">
      <div class="row"><div><label>자막 크기</label><input class="sizeIn" type="number" value="${p.caption_style.size}"></div>
      <div><label>자막 위치</label><select class="posIn">${["top", "middle", "bottom"].map((x) => `<option value="${x}"${x === p.caption_style.pos ? " selected" : ""}>${{ top: "위", middle: "가운데", bottom: "아래" }[x]}</option>`).join("")}</select></div></div>
      <div class="row"><div><label>길이</label><select class="durIn">${DUR_OPTS(p.duration)}</select></div>
      <div><label>밝기</label><select class="brIn"><option value="0">그대로</option><option value="0.05">밝게</option><option value="0.1">더 밝게</option><option value="-0.05">어둡게</option></select></div></div>
      <button class="btn gold block" onclick="rerender(${r.id})">수정본 만들기 (이전 버전 보존)</button>
    </details>
    ${r.sns ? `<details><summary>SNS 게시 문구</summary>${Object.entries(r.sns).filter(([k]) => k !== "notice").map(([k, v]) => `<div class="small muted">${k}</div><div class="copybox">${esc(v)}</div><button class="btn sm" onclick='copyText(${JSON.stringify(v).replace(/'/g, "&#39;")})'>복사</button>`).join("")}</details>` : ""}
    ${c.items ? `<details><summary>제작 원가 ${won(c.total_krw)} · 예상 이익 ${won(c.profit_krw)}</summary><table>
      ${c.items.map((it) => `<tr><td>${esc(it.name)}${it.estimated ? ' <span class="muted">(추정)</span>' : ""}<div class="muted small">${esc(it.basis)}</div></td><td class="right">${won(it.krw)}</td></tr>`).join("")}
      <tr><td>판매가</td><td class="right">${won(c.price)}</td></tr></table><p class="small muted">렌더링 ${c.render_seconds}초</p></details>` : ""}
  </div>`;
}

async function produce(id, variants) {
  try {
    const r = await api(`/api/admin/orders/${id}/produce`, { method: "POST", body: form({ style: $("#pStyle").value, duration: $("#pDur").value, variants, hook_text: $("#pHook").value }) });
    const wait = r.jobs.filter((j) => j.status === "awaiting_approval");
    toast(wait.length ? `비용 한도 때문에 승인 대기: ${wait[0].reason}` : `${r.jobs.length}개 제작을 시작했습니다`, 4000);
    viewOrder(id);
  } catch (e) { toast(e.message); }
}

async function rerender(rid) {
  const c = $("#r" + rid);
  const body = { hook_text: $(".hookIn", c).value, cta_text: $(".ctaIn", c).value, captions: $$(".capIn", c).map((x) => x.value),
    caption_size: $(".sizeIn", c).value, caption_pos: $(".posIn", c).value, duration: +$(".durIn", c).value, brightness: +$(".brIn", c).value,
    end_card: { address: $(".addrIn", c).value, phone: $(".phoneIn", c).value } };
  try { await api(`/api/admin/renders/${rid}/rerender`, { method: "POST", json: body }); toast("수정본 제작을 시작했습니다"); route(); } catch (e) { toast(e.message); }
}

async function approve(rid) {
  if (!confirm("이 영상을 고객에게 전달할까요?")) return;
  await api(`/api/admin/renders/${rid}/approve`, { method: "POST" }); toast("고객에게 전달했습니다"); route();
}

async function retryJob(jid) { await api(`/api/admin/jobs/${jid}/retry`, { method: "POST" }); toast("다시 실행합니다"); route(); }
async function cancelJob(jid) { await api(`/api/admin/jobs/${jid}/cancel`, { method: "POST" }); toast("취소했습니다"); route(); }

// ---------------- 대리 접수 ----------------
async function viewNewOrder() {
  const prods = CAT.products;
  V().innerHTML = `<h1>고객 영상 대신 접수</h1><p class="muted">카카오톡 등으로 받은 영상을 휴대폰에 저장한 뒤 올려 주세요.</p>
  <div class="card"><label>고객 이름</label><input id="customer_name"><label>고객 휴대폰</label><input id="customer_phone" type="tel">
  <label>고객 이메일 <span class="opt">(선택)</span></label><input id="customer_email" type="email"></div>
  <div class="card"><label>상호명 *</label><input id="biz_name"><label>업종 *</label><div class="chips" id="industry"></div>
  <label>주소</label><input id="address"><label>전화번호</label><input id="biz_phone" type="tel"><label>홈페이지/SNS</label><input id="website">
  <label>주요 상품·서비스</label><div class="mic"><textarea id="products"></textarea></div>
  <label>꼭 넣을 문구</label><div class="mic"><textarea id="highlights"></textarea></div></div>
  <div class="card"><label>홍보 목적</label><div class="chips" id="purpose"></div><label>분위기</label><div class="chips" id="mood"></div>
  <label>스타일</label><div class="chips" id="style"></div><label>길이</label><div class="chips" id="duration"></div>
  <label>상품</label><div class="chips" id="product_code"></div></div>
  <div class="card"><label>영상·사진 *</label><input id="files" type="file" multiple accept="video/*,image/*"><label>로고</label><input id="logo" type="file" accept="image/*"></div>
  <div id="upbox" class="card hidden"><div class="progress"><i id="upbar"></i></div><div id="uptext" class="small muted"></div></div>
  <button class="btn gold block" id="submit">접수하고 바로 제작</button>`;
  chips($("#industry"), CAT.industries); chips($("#purpose"), CAT.purposes, { value: "visit" }); chips($("#mood"), CAT.moods, { value: "bright" });
  chips($("#style"), { auto: "인기 패턴 자동", ...CAT.styles }, { value: "trend" });
  chips($("#duration"), Object.fromEntries(CAT.durations.map((d) => [String(d), d + "초"])), { value: "30" });
  chips($("#product_code"), Object.fromEntries(prods.map((p) => [p.code, `${p.name} ${p.price ? won(p.price) : ""}`])), { value: "basic" });
  enableVoice();
  $("#submit").onclick = async () => {
    const v = (i) => ($("#" + i).dataset.value ?? $("#" + i).value ?? "").trim();
    const keys = ["customer_name", "customer_phone", "customer_email", "biz_name", "industry", "address", "biz_phone", "website", "products", "highlights", "purpose", "mood", "style", "duration", "product_code"];
    const fd = form(Object.fromEntries(keys.map((k) => [k, v(k)])));
    [...$("#files").files].forEach((f) => fd.append("files", f));
    if ($("#logo").files[0]) fd.append("logo", $("#logo").files[0]);
    if (!$("#files").files.length) return toast("영상을 선택해 주세요");
    $("#submit").disabled = true; $("#upbox").classList.remove("hidden");
    try { const r = await upload("/api/admin/orders", fd, (p) => { $("#upbar").style.width = p + "%"; $("#uptext").textContent = p + "%"; });
      toast("접수했습니다. 제작을 시작합니다."); location.hash = "#order/" + r.order_id;
    } catch (e) { toast(e.message, 5000); $("#submit").disabled = false; }
  };
}

// ---------------- 벤치마킹 ----------------
const REF_TEXT = { hook_type: "후킹 방식", hook_text: "첫 문장/후킹 문구", edit_pattern: "편집 패턴", caption_style: "자막 스타일",
  music_mood: "음악 분위기", story_structure: "스토리 구성", cta_type: "구매/방문 유도 방식", notes: "메모(감정 유발 요소·카메라 구도 등)" };

async function viewRefs() {
  const ind = store.get("refInd", "");
  const rows = await api("/api/admin/references" + (ind ? `?industry=${ind}` : ""));
  const pat = ind ? await api(`/api/admin/patterns/${ind}`) : null;
  V().innerHTML = `<h1>인기 숏폼 벤치마킹</h1>
  <p class="muted small">공식 API(유튜브) 또는 관리자가 확인한 자료만 저장합니다. 확인 못 한 수치는 비워 두세요. 영상의 '패턴'만 참고하며 원본을 복제하지 않습니다.</p>
  <div class="chips" id="indf"></div>
  ${pat ? `<div class="card small"><b>이 업종의 적용 패턴</b> (참고 ${pat.count}개${pat.scope === "all" ? ", 전체 업종 기준" : ""})<br>
    평균 컷 길이 ${pat.avg_cut_sec ?? "-"}초 · 평균 길이 ${pat.avg_duration ?? "-"}초<br>후킹: ${esc(pat.hook_type || "-")} · 구성: ${esc(pat.story_structure || "-")} · 유도: ${esc(pat.cta_type || "-")}<br>
    자막 위치: ${esc(pat.caption_position || "-")} · 추천 스타일: ${esc(CAT.styles[pat.template_style] || "-")}</div>` : ""}
  <details id="addBox"><summary>➕ 참고 영상·패턴 등록</summary>
    <label>업종 *</label><select id="r_industry">${Object.entries(CAT.industries).map(([k, v]) => `<option value="${k}"${k === ind ? " selected" : ""}>${v}</option>`).join("")}</select>
    <label>영상 링크</label><input id="r_url" placeholder="유튜브 쇼츠 / 릴스 / 틱톡 링크">
    <label>제목</label><input id="r_title">
    <label>참고 영상 파일 <span class="opt">(적법하게 확보한 경우만 — 컷 길이 등을 자동 측정)</span></label><input id="r_video" type="file" accept="video/*">
    <div class="row"><div><label>조회수</label><input id="r_views" inputmode="numeric"></div><div><label>좋아요</label><input id="r_likes" inputmode="numeric"></div></div>
    <div class="row"><div><label>댓글</label><input id="r_comments" inputmode="numeric"></div><div><label>공유</label><input id="r_shares" inputmode="numeric"></div></div>
    <div class="row"><div><label>채널 구독자</label><input id="r_channel_subscribers" inputmode="numeric"></div><div><label>게시일</label><input id="r_published_at" type="date"></div></div>
    ${Object.entries(REF_TEXT).map(([k, l]) => `<label>${l}</label><div class="mic"><input id="r_${k}"></div>`).join("")}
    <div class="row"><div><label>자막 위치</label><select id="r_caption_position"><option value="">-</option><option value="top">위</option><option value="middle">가운데</option><option value="bottom">아래</option></select></div>
    <div><label>적용할 편집 스타일</label><select id="r_template_style"><option value="">-</option>${STYLE_OPTS()}</select></div></div>
    <button class="btn gold block" id="refAdd">등록</button>
  </details>
  <div id="list">${rows.map(refCard).join("") || '<div class="card muted">등록된 자료가 없습니다.</div>'}</div>`;
  chips($("#indf"), { "": "전체", ...CAT.industries }, { value: ind });
  $("#indf").addEventListener("click", () => { store.set("refInd", $("#indf").dataset.value); viewRefs(); });
  enableVoice();
  $("#refAdd").onclick = async () => {
    const fd = new FormData();
    ["industry", "url", "title", "views", "likes", "comments", "shares", "channel_subscribers", "published_at", "caption_position", "template_style", ...Object.keys(REF_TEXT)]
      .forEach((k) => fd.append(k, $("#r_" + k).value));
    if ($("#r_video").files[0]) fd.append("video", $("#r_video").files[0]);
    try { const r = await upload("/api/admin/references", fd); toast(r.warning || (r.job_id ? "등록했습니다. 영상 분석을 시작합니다." : "등록했습니다"), 4000); viewRefs(); }
    catch (e) { toast(e.message); }
  };
}

function refCard(r) {
  const m = r.metrics || {}, man = m.manual || {}, me = m.measured;
  const val = (k) => (m[k] ?? man[k]);
  const src = m.source === "youtube_api" ? "유튜브 API" : (Object.keys(man).length ? "관리자 입력" : "");
  return `<div class="card small">
    <div class="row" style="align-items:center"><div style="flex:3"><b>${esc(r.title || r.url || "제목 없음")}</b><br>
      <span class="muted">${esc(CAT.industries[r.industry])} · ${esc(r.platform)} · 신뢰도 ${({ low: "낮음", medium: "보통", high: "높음" })[r.reliability]}</span></div>
      <div style="flex:1;text-align:right">${r.active ? '<span class="status s-done">사용 중</span>' : '<span class="status s-awaiting_approval">검토 필요</span>'}</div></div>
    ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">링크 열기</a><br>` : ""}
    ${val("views") != null ? `조회수 ${Number(val("views")).toLocaleString()} · 좋아요 ${val("likes") ?? "-"} · 댓글 ${val("comments") ?? "-"} · 공유 ${val("shares") ?? "확인 불가"} <span class="muted">(${src})</span><br>` : '<span class="muted">반응 데이터 없음</span><br>'}
    ${m.views_per_day ? `하루 평균 조회 ${m.views_per_day.toLocaleString()} · 구독자 대비 ${m.views_per_subscriber ?? "-"}배 <span class="muted">(광고 집행 여부 확인 불가)</span><br>` : ""}
    ${me ? `측정: 길이 ${me.duration}초 · 컷 ${me.scene_cuts}회 · 평균 컷 ${me.avg_cut_sec}초 · 첫 3초 컷 ${me.first3s_cuts}회<br>` : (r.video_path ? '<span class="muted">영상 분석 대기 중…</span><br>' : "")}
    ${Object.entries(REF_TEXT).filter(([k]) => r[k]).map(([k, l]) => `${l}: ${esc(r[k])}`).join("<br>")}
    <div class="row" style="margin-top:8px"><button class="btn sm" onclick="refToggle(${r.id},${r.active ? 0 : 1})">${r.active ? "사용 중지" : "사용하기"}</button>
    <button class="btn sm" onclick="refEdit(${r.id})">수정</button><button class="btn red sm" onclick="refDel(${r.id})">삭제</button></div></div>`;
}

async function refToggle(id, active) { await api(`/api/admin/references/${id}`, { method: "PUT", json: { active } }); viewRefs(); }
async function refDel(id) { if (!confirm("삭제할까요?")) return; await api(`/api/admin/references/${id}`, { method: "DELETE" }); viewRefs(); }
async function refEdit(id) {
  const field = prompt("수정할 항목을 입력하세요:\n" + Object.entries(REF_TEXT).map(([k, l]) => `${l}`).join(", ") + ", 평균 컷 길이");
  if (!field) return;
  const key = field === "평균 컷 길이" ? "avg_cut_sec" : Object.entries(REF_TEXT).find(([, l]) => l === field.trim())?.[0];
  if (!key) return toast("항목 이름을 정확히 입력해 주세요");
  const value = prompt(field + " 값");
  if (value === null) return;
  await api(`/api/admin/references/${id}`, { method: "PUT", json: { [key]: value } }); toast("수정했습니다"); viewRefs();
}

// ---------------- 작업 ----------------
async function viewJobs() {
  const rows = await api("/api/admin/jobs");
  V().innerHTML = `<h1>자동화 작업</h1><p class="muted small">서버에서 실행되는 작업 목록입니다. 실패한 작업은 다시 실행할 수 있습니다.</p>
  ${rows.map((j) => `<div class="card small"><b>#${j.id}</b> ${j.type === "produce" ? "영상 제작" : "참고 영상 분석"} ${j.order_id ? `· <a href="#order/${j.order_id}">주문 #${j.order_id}</a>` : ""} ${j.style ? "· " + esc(CAT.styles[j.style] || j.style) : ""}
    <br>${statusChip(j.status)} ${j.status === "running" ? `${j.progress}% ${esc(j.step)}` : ""} <span class="muted">시도 ${j.attempts}회 · ${esc((j.created_at || "").slice(5, 16).replace("T", " "))}</span>
    ${j.estimate ? `<br><span class="muted">예상 원가 ${won(j.estimate.total_krw)}</span>` : ""}
    ${j.error ? `<div class="warn">${esc(j.error)}</div>` : ""}
    ${["failed", "awaiting_approval"].includes(j.status) ? `<div class="row"><button class="btn sm gold" onclick="retryJob(${j.id})">${j.status === "failed" ? "다시 실행" : "승인하고 실행"}</button>${j.status === "awaiting_approval" ? `<button class="btn sm" onclick="cancelJob(${j.id})">취소</button>` : ""}</div>` : ""}
  </div>`).join("") || '<div class="card muted">작업이 없습니다.</div>'}`;
  if (rows.some((j) => ["queued", "running"].includes(j.status))) pollTimer = setInterval(viewJobs, 5000);
}

// ---------------- 관리 메뉴 ----------------
async function viewMore() {
  V().innerHTML = `<h1>관리</h1>
  ${[["#customers", "👥 고객·수익성"], ["#payments", "💳 결제 내역"], ["#products", "🏷️ 상품·가격"], ["#music", "🎵 배경음악(라이선스)"],
    ["#settings", "💰 비용 한도 설정"], ["#system", "🛠️ 시스템 상태·API 연결"]].map(([h, l]) => `<a class="btn block" href="${h}">${l}</a>`).join("")}`;
}

async function viewCustomers() {
  const rows = await api("/api/admin/customers");
  V().innerHTML = `<h1>고객·수익성</h1><p class="muted small">원가에는 추정치가 포함됩니다(주문 상세에서 항목별 확인).</p><div class="card"><table>
  <tr><th>고객</th><th class="right">주문</th><th class="right">매출</th><th class="right">이익</th></tr>
  ${rows.map((u) => `<tr><td>${esc(u.name || u.email)}<div class="muted">${esc(u.phone)}</div></td><td class="right">${u.orders}</td><td class="right">${won(u.revenue)}</td><td class="right">${won(u.profit)}</td></tr>`).join("")}
  </table></div>`;
}

async function viewPayments() {
  const rows = await api("/api/admin/payments");
  V().innerHTML = `<h1>결제 내역</h1><p class="muted small">카드 결제 연동 전이라 입금 확인을 수동으로 기록합니다(주문 상세 → 결제).</p><div class="card"><table>
  ${rows.map((p) => `<tr><td>${p.created_at.slice(0, 10)}<div class="muted">${esc(p.biz_name || "")} #${p.order_id}</div></td><td>${esc(p.memo)}</td><td class="right">${won(p.amount)}</td></tr>`).join("") || "<tr><td>없음</td></tr>"}
  </table></div>`;
}

async function viewProducts() {
  const rows = await api("/api/admin/products");
  V().innerHTML = `<h1>상품·가격</h1>${rows.map((p) => `<div class="card"><label>${esc(p.code)}</label><input id="pn_${p.code}" value="${esc(p.name)}">
    <div class="row"><div><label>가격(원)</label><input id="pp_${p.code}" type="number" inputmode="numeric" value="${p.price}"></div>
    <div><label>판매</label><select id="pa_${p.code}"><option value="1"${p.active ? " selected" : ""}>판매 중</option><option value="0"${p.active ? "" : " selected"}>중지</option></select></div></div>
    <button class="btn sm block" onclick="saveProduct('${p.code}')">저장</button></div>`).join("")}`;
}
async function saveProduct(code) {
  await api(`/api/admin/products/${code}`, { method: "PUT", json: { name: $("#pn_" + code).value, price: +$("#pp_" + code).value, active: $("#pa_" + code).value === "1" } });
  toast("저장했습니다");
}

const SET_LABEL = { monthly_ai_budget_krw: "월 AI 사용료 한도(원)", monthly_server_budget_krw: "월 서버비 한도(원)", per_job_cost_limit_krw: "영상 1편 예상 원가 한도(원) — 넘으면 승인 필요",
  server_monthly_cost_krw: "실제 월 서버비(원) — 원가 계산용", expected_monthly_videos: "월 예상 제작 편수 — 서버비 배분용", retention_days: "원본 영상 보관 기간(일, 전달 완료 후)" };
async function viewSettings() {
  const s = await api("/api/admin/settings");
  V().innerHTML = `<h1>비용 한도 설정</h1><div class="card">${Object.entries(SET_LABEL).map(([k, l]) => `<label>${l}</label><input id="s_${k}" inputmode="numeric" value="${esc(s[k] ?? "")}">`).join("")}
  <button class="btn gold block" id="save">저장</button></div>`;
  $("#save").onclick = async () => { try { await api("/api/admin/settings", { method: "PUT", json: Object.fromEntries(Object.keys(SET_LABEL).map((k) => [k, $("#s_" + k).value.trim()])) }); toast("저장했습니다"); } catch (e) { toast(e.message); } };
}

async function viewMusic() {
  const rows = await api("/api/admin/music");
  V().innerHTML = `<h1>배경음악</h1><div class="warn small">상업적 이용이 허용된 음원만 등록하세요. 출처와 이용 조건을 반드시 기록합니다. (예: YouTube 오디오 보관함의 '저작자 표시 필요 없음' 음원, 유료 구독 음원 라이선스)</div>
  <details><summary>➕ 음원 등록</summary><label>음원 파일</label><input id="m_file" type="file" accept="audio/*">
  <label>제목</label><input id="m_title"><label>분위기</label><select id="m_mood">${Object.entries(CAT.moods).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
  <label>BPM <span class="opt">(알면 입력 — 박자에 맞춰 장면 전환)</span></label><input id="m_bpm" inputmode="decimal">
  <label>출처 *</label><input id="m_src" placeholder="예) YouTube 오디오 보관함"><label>이용 조건 *</label><input id="m_terms" placeholder="예) 상업적 이용 가능, 저작자 표시 불필요">
  <label><input id="m_ok" type="checkbox" style="width:auto"> 상업적 이용이 허용된 음원임을 확인했습니다</label>
  <button class="btn gold block" id="mAdd">등록</button></details>
  ${rows.map((m) => `<div class="card small"><b>${esc(m.title)}</b> · ${esc(CAT.moods[m.mood] || m.mood)} ${m.bpm ? "· " + m.bpm + "BPM" : ""} · ${Math.round(m.duration_sec)}초<br>
    <span class="muted">${esc(m.license_source)} / ${esc(m.license_terms)}</span><br>
    <button class="btn sm" onclick="api('/api/admin/music/${m.id}/toggle',{method:'POST'}).then(viewMusic)">${m.active ? "사용 중 (끄기)" : "꺼짐 (켜기)"}</button></div>`).join("") || '<div class="card muted">등록된 음원이 없습니다. 음원이 없으면 원본 영상의 소리를 사용합니다.</div>'}`;
  $("#mAdd").onclick = async () => {
    if (!$("#m_file").files[0]) return toast("파일을 선택해 주세요");
    const fd = form({ title: $("#m_title").value, mood: $("#m_mood").value, bpm: $("#m_bpm").value, license_source: $("#m_src").value, license_terms: $("#m_terms").value, commercial_ok: $("#m_ok").checked ? "1" : "0" });
    fd.append("file", $("#m_file").files[0]);
    try { await upload("/api/admin/music", fd); toast("등록했습니다"); viewMusic(); } catch (e) { toast(e.message); }
  };
}

async function viewSystem() {
  const s = await api("/api/admin/system");
  V().innerHTML = `<h1>시스템 상태</h1><div class="card small">버전 ${esc(s.version)} (${esc(s.env)})<br>${esc(s.ffmpeg)}<br>
    저장 공간: ${s.disk_free_gb}GB 남음 / ${s.disk_total_gb}GB<br>자막 글꼴: ${s.font_exists ? "정상" : "없음!"}<br>최근 작업 활동: ${esc(s.last_job_activity || "-")}</div>
    <h2>외부 서비스 연결</h2>${Object.entries(s.integrations).map(([k, v]) => `<div class="card small"><b>${k}</b> ${v.configured ? '<span class="status s-done">연결됨</span>' : '<span class="status">미연결</span>'}<br>
    <span class="muted">${esc(v.desc)}</span>${v.error ? `<div class="warn">${esc(v.error)}</div>` : ""}</div>`).join("")}
    <p class="muted small">API 키는 보안을 위해 화면이 아닌 서버 환경변수에서 설정합니다(배포 안내서 참고).</p>`;
}

boot().catch((e) => { V().innerHTML = `<div class="card">서버에 연결할 수 없습니다. ${esc(e.message)}</div>`; });

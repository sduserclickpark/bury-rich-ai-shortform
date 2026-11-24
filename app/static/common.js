// 공통 도우미
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const won = (n) => (Math.round(Number(n || 0))).toLocaleString("ko-KR") + "원";
const STATUS = { received: "접수", processing: "제작 중", review: "검수 대기", delivered: "완성", revision: "수정 요청", failed: "실패", canceled: "취소",
  queued: "대기", running: "진행 중", done: "완료", awaiting_approval: "승인 필요" };
const statusChip = (s) => `<span class="status s-${esc(s)}">${esc(STATUS[s] || s)}</span>`;

async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { /* 비어 있는 응답 */ }
  if (!r.ok) throw new Error((data && data.detail) || `오류가 발생했습니다 (${r.status})`);
  return data;
}

function form(obj) { const f = new FormData(); Object.entries(obj).forEach(([k, v]) => f.append(k, v)); return f; }

function toast(msg, ms = 2600) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
  toast("복사했습니다");
}

// 업로드 진행률 표시가 필요한 요청(XHR)
function upload(path, fd, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", path);
    x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(Math.round((e.loaded / e.total) * 100));
    x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch (e) {}
      x.status < 300 ? resolve(d) : reject(new Error(d.detail || `업로드 실패 (${x.status})`)); };
    x.onerror = () => reject(new Error("네트워크 오류로 업로드에 실패했습니다. 와이파이 연결을 확인해 주세요."));
    x.send(fd);
  });
}

// 스마트폰 음성 입력(크롬 안드로이드 지원). textarea/input 을 .mic 로 감싸면 마이크 버튼이 생긴다.
function enableVoice(root = document) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  $$(".mic", root).forEach((w) => {
    if ($("button", w)) return;
    const field = $("textarea,input", w);
    const b = document.createElement("button");
    b.type = "button"; b.textContent = "🎤"; b.title = "음성 입력";
    b.onclick = () => {
      const r = new SR(); r.lang = "ko-KR"; r.interimResults = false;
      b.classList.add("rec");
      r.onresult = (e) => { const t = e.results[0][0].transcript; field.value = (field.value ? field.value + " " : "") + t; field.dispatchEvent(new Event("input")); };
      r.onend = () => b.classList.remove("rec");
      r.onerror = () => { b.classList.remove("rec"); toast("음성 인식을 사용할 수 없습니다"); };
      r.start();
    };
    w.appendChild(b);
  });
}

function chips(container, options, { multi = false, value = "", name } = {}) {
  container.innerHTML = Object.entries(options).map(([k, v]) => `<span class="chip${k === value ? " on" : ""}" data-v="${esc(k)}">${esc(v)}</span>`).join("");
  container.dataset.value = value;
  container.onclick = (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    if (multi) { c.classList.toggle("on"); container.dataset.value = $$(".chip.on", container).map((x) => x.dataset.v).join(","); }
    else { $$(".chip", container).forEach((x) => x.classList.remove("on")); c.classList.add("on"); container.dataset.value = c.dataset.v; }
  };
}

const store = {
  get(k, d = null) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};

if ("serviceWorker" in navigator) { navigator.serviceWorker.register("/sw.js").catch(() => {}); }

"""웹 서버(API + 모바일 화면). 실행: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import re
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth, config, db
from .services import benchmark, costs, planner
from .services.catalog import AGES, INDUSTRIES, MOODS, PURPOSES, STYLES

@asynccontextmanager
async def lifespan(_app):
    db.init()
    auth.ensure_admin(config.ADMIN_EMAIL, config.ADMIN_PASSWORD)
    yield


app = FastAPI(title="BURY RICH AI SHORTFORM STUDIO", version=__version__, docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, max_age=60 * 60 * 24 * 30,
                   same_site="lax", https_only=config.APP_ENV == "production")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".webm", ".mkv", ".avi"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


# ---------------- 화면 ----------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/healthz")
def health():
    return {"ok": True, "version": __version__}


# ---------------- 공통 ----------------

@app.get("/api/catalog")
def catalog():
    return {
        "industries": INDUSTRIES, "purposes": PURPOSES, "ages": AGES, "moods": MOODS,
        "styles": {k: v["name"] for k, v in STYLES.items()}, "durations": list(config.ALLOWED_DURATIONS),
        "products": db.q("SELECT * FROM products WHERE active=1 ORDER BY sort"),
    }


@app.post("/api/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...), name: str = Form(""),
           phone: str = Form("")):
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "이메일 형식이 올바르지 않습니다.")
    if len(password) < 8:
        raise HTTPException(400, "비밀번호는 8자 이상이어야 합니다.")
    if db.q1("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(400, "이미 가입된 이메일입니다.")
    uid = db.run("INSERT INTO users(email,password_hash,name,phone,created_at) VALUES (?,?,?,?,?)",
                 (email, auth.hash_password(password), name.strip(), phone.strip(), db.now()))
    request.session["uid"] = uid
    return {"ok": True}


@app.post("/api/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    u = db.q1("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
    if not u or not auth.verify_password(password, u["password_hash"]):
        raise HTTPException(400, "이메일 또는 비밀번호가 맞지 않습니다.")
    request.session["uid"] = u["id"]
    return {"ok": True, "role": u["role"]}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return {"user": auth.current_user(request)}


# ---------------- 주문 생성(고객 / 관리자 대리 접수 공통) ----------------

async def _save_upload(f: UploadFile, dest_dir: Path) -> tuple[str, int, str]:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in VIDEO_EXT | IMAGE_EXT:
        raise HTTPException(400, f"지원하지 않는 파일 형식입니다: {f.filename}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with open(dest, "wb") as out:
        while chunk := await f.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"파일이 너무 큽니다(최대 {config.MAX_UPLOAD_MB}MB): {f.filename}")
            out.write(chunk)
    kind = "video" if ext in VIDEO_EXT else "image"
    return str(dest), size, kind


def _enqueue(job_type: str, payload: dict) -> int:
    return db.run("INSERT INTO jobs(type,payload_json,status,created_at) VALUES (?,?,?,?)",
                  (job_type, db.jdump(payload), "queued", db.now()))


def _enqueue_produce(order_id: int, payload: dict) -> dict:
    """비용 한도를 확인하고 작업을 대기열에 넣는다. 한도 초과 예상 시 관리자 승인 대기."""
    media = db.q("SELECT kind FROM media WHERE order_id=?", (order_id,))
    est = costs.estimate_job_krw(len(media), 0)
    limit_job = float(db.setting("per_job_cost_limit_krw", "1000"))
    budget = float(db.setting("monthly_ai_budget_krw", "50000"))
    spent = costs.month_ai_spend_krw()
    status = "queued"
    reason = ""
    if est["total_krw"] > limit_job:
        status, reason = "awaiting_approval", f"예상 원가 {est['total_krw']}원이 1편 한도 {limit_job:.0f}원 초과"
    elif spent + est["ai_krw"] > budget:
        status, reason = "awaiting_approval", f"이번 달 AI 사용료 {spent}원 + 예상 {est['ai_krw']}원이 월 한도 {budget:.0f}원 초과"
    payload = {**payload, "order_id": order_id, "estimate": est}
    jid = db.run("INSERT INTO jobs(type,payload_json,status,error,created_at) VALUES (?,?,?,?,?)",
                 ("produce", db.jdump(payload), status, reason, db.now()))
    return {"job_id": jid, "status": status, "reason": reason, "estimate": est}


async def _create_order(user_id: int, form: dict, files: list[UploadFile], logo: UploadFile | None,
                        auto_start: bool) -> dict:
    name = (form.get("biz_name") or "").strip()
    industry = form.get("industry") or ""
    if not name:
        raise HTTPException(400, "상호명을 입력해 주세요.")
    if industry not in INDUSTRIES:
        raise HTTPException(400, "업종을 선택해 주세요.")
    files = [f for f in files if f and f.filename]
    if not files:
        raise HTTPException(400, "영상 또는 사진을 1개 이상 올려 주세요.")
    duration = int(form.get("duration") or 30)
    if duration not in config.ALLOWED_DURATIONS:
        raise HTTPException(400, "영상 길이는 15/30/45/60초 중에서 선택해 주세요.")
    style = form.get("style") or "trend"
    if style not in STYLES and style != "auto":
        style = "trend"
    product_code = form.get("product_code") or "free_trial"
    prod = db.q1("SELECT * FROM products WHERE code=? AND active=1", (product_code,))
    if not prod:
        raise HTTPException(400, "상품을 선택해 주세요.")
    user = db.q1("SELECT * FROM users WHERE id=?", (user_id,))
    if product_code == "free_trial" and user["free_trial_used"] and user["role"] != "admin":
        raise HTTPException(400, "무료 체험은 1회만 이용할 수 있습니다. 다른 상품을 선택해 주세요.")

    now = db.now()
    biz_id = db.run(
        "INSERT INTO businesses(user_id,name,industry,address,phone,website,products,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, name, industry, form.get("address", "").strip(), form.get("biz_phone", "").strip(),
         form.get("website", "").strip(), form.get("products", "").strip(), now))
    order_id = db.run(
        "INSERT INTO orders(user_id,business_id,product_code,purpose,target_age,mood,style,duration,reference_links,"
        "request_note,highlights,status,price,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, biz_id, product_code, form.get("purpose", ""), form.get("target_age", ""), form.get("mood", ""),
         style, duration, form.get("reference_links", "").strip(), form.get("request_note", "").strip(),
         form.get("highlights", "").strip(), "received", prod["price"], now, now))
    dest = config.UPLOAD_DIR / f"order{order_id}"
    for f in files:
        path, size, kind = await _save_upload(f, dest)
        db.run("INSERT INTO media(order_id,kind,original_name,path,size_bytes,created_at) VALUES (?,?,?,?,?,?)",
               (order_id, kind, (f.filename or "")[:200], path, size, now))
    if logo and logo.filename:
        path, _, kind = await _save_upload(logo, dest)
        if kind != "image":
            raise HTTPException(400, "로고는 이미지 파일로 올려 주세요.")
        db.run("UPDATE businesses SET logo_path=? WHERE id=?", (path, biz_id))
    if product_code == "free_trial":
        db.run("UPDATE users SET free_trial_used=1 WHERE id=?", (user_id,))
    # 고객이 남긴 참고 링크는 벤치마킹 후보로 저장(관리자 검토 전까지 비활성)
    for link in re.findall(r"https?://\S+", form.get("reference_links", "")):
        db.run("INSERT INTO references_db(industry,platform,url,notes,active,created_at) VALUES (?,?,?,?,0,?)",
               (industry, benchmark.detect_platform(link), link, f"고객 주문 #{order_id} 참고 링크(검토 필요)", now))
    job = _enqueue_produce(order_id, {"style": style, "duration": duration}) if auto_start else None
    from .services import notify
    notify.admin(f"신규 주문 #{order_id} {name} ({prod['name']})")
    return {"order_id": order_id, "job": job}


@app.post("/api/orders")
async def create_order(request: Request, files: list[UploadFile] = File(...), logo: UploadFile | None = File(None),
                       user=Depends(auth.require_user)):
    form = dict((await request.form()).items())
    form = {k: v for k, v in form.items() if isinstance(v, str)}
    return await _create_order(user["id"], form, files, logo, auto_start=True)


def _order_view(o: dict, admin: bool) -> dict:
    o = dict(o)
    o["business"] = db.q1("SELECT * FROM businesses WHERE id=?", (o["business_id"],))
    o["renders"] = []
    for r in db.q("SELECT * FROM renders WHERE order_id=? ORDER BY version DESC", (o["id"],)):
        if not admin and not r["approved"]:
            continue
        r["plan"] = db.jload(r["plan_json"])
        r["sns"] = db.jload(r["sns_json"])
        r["cost"] = db.jload(r["cost_json"]) if admin else None
        for k in ("plan_json", "sns_json", "cost_json", "output_path", "thumb_path"):
            r.pop(k, None)
        if not admin:
            r["plan"] = {k: r["plan"].get(k) for k in ("title", "hook_text", "style_name", "duration")}
        o["renders"].append(r)
    media = db.q("SELECT id,kind,original_name,size_bytes,analysis_json,path FROM media WHERE order_id=?", (o["id"],))
    for m in media:
        a = db.jload(m.pop("analysis_json"))
        m["deleted"] = not m.pop("path")
        m["overall"] = a.get("overall")
        m["transcript"] = a.get("transcript") if admin else None
        if admin:
            m["segments"] = [{k: s.get(k) for k in ("start", "end", "score", "issues", "usable", "duplicate_of")}
                             for s in a.get("segments", [])]
    o["media"] = media
    job = db.q1("SELECT id,status,progress,step,error,attempts FROM jobs WHERE type='produce' AND "
                "json_extract(payload_json,'$.order_id')=? ORDER BY id DESC LIMIT 1", (o["id"],))
    o["job"] = job
    o["revisions"] = db.q("SELECT * FROM revisions WHERE order_id=? ORDER BY id DESC", (o["id"],))
    return o


@app.get("/api/orders")
def my_orders(user=Depends(auth.require_user)):
    rows = db.q("SELECT o.*, b.name biz_name FROM orders o JOIN businesses b ON b.id=o.business_id "
                "WHERE o.user_id=? ORDER BY o.id DESC", (user["id"],))
    return [_order_view(o, admin=False) for o in rows]


def _own_order(order_id: int, user: dict) -> dict:
    o = db.q1("SELECT * FROM orders WHERE id=?", (order_id,))
    if not o or (o["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    return o


@app.get("/api/orders/{order_id}")
def order_detail(order_id: int, user=Depends(auth.require_user)):
    return _order_view(_own_order(order_id, user), admin=False)


@app.post("/api/orders/{order_id}/revision")
def request_revision(order_id: int, message: str = Form(...), user=Depends(auth.require_user)):
    o = _own_order(order_id, user)
    if not message.strip():
        raise HTTPException(400, "수정 요청 내용을 입력해 주세요.")
    db.run("INSERT INTO revisions(order_id,requested_by,message,created_at) VALUES (?,?,?,?)",
           (o["id"], "customer", message.strip()[:2000], db.now()))
    db.run("UPDATE orders SET status='revision', updated_at=? WHERE id=?", (db.now(), o["id"]))
    from .services import notify
    notify.admin(f"수정 요청 — 주문 #{o['id']}: {message.strip()[:100]}")
    return {"ok": True}


@app.post("/api/orders/{order_id}/rating")
def rate(order_id: int, rating: int = Form(...), feedback: str = Form(""), user=Depends(auth.require_user)):
    o = _own_order(order_id, user)
    if not 1 <= rating <= 5:
        raise HTTPException(400, "평점은 1~5 사이입니다.")
    db.run("UPDATE orders SET rating=?, feedback=?, updated_at=? WHERE id=?",
           (rating, feedback.strip()[:2000], db.now(), o["id"]))
    return {"ok": True}


@app.post("/api/orders/{order_id}/delete-sources")
def delete_sources(order_id: int, user=Depends(auth.require_user)):
    """고객 요청 시 원본 영상 삭제(완성본은 남김)."""
    o = _own_order(order_id, user)
    for m in db.q("SELECT id,path FROM media WHERE order_id=?", (o["id"],)):
        if m["path"]:
            Path(m["path"]).unlink(missing_ok=True)
        db.run("UPDATE media SET path='' WHERE id=?", (m["id"],))
    return {"ok": True}


# ---------------- 파일 전송(권한 확인) ----------------

def _render_for(render_id: int, user: dict) -> dict:
    r = db.q1("SELECT r.*, o.user_id FROM renders r JOIN orders o ON o.id=r.order_id WHERE r.id=?", (render_id,))
    if not r or (user["role"] != "admin" and (r["user_id"] != user["id"] or not r["approved"])):
        raise HTTPException(404, "영상을 찾을 수 없습니다.")
    return r


@app.get("/files/render/{render_id}.mp4")
def render_file(render_id: int, download: int = 0, user=Depends(auth.require_user)):
    r = _render_for(render_id, user)
    p = Path(r["output_path"])
    if not p.exists():
        raise HTTPException(404, "파일이 없습니다.")
    name = f"shortform_{r['order_id']}_v{r['version']}.mp4"
    return FileResponse(p, media_type="video/mp4", filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/files/render/{render_id}.jpg")
def render_thumb(render_id: int, user=Depends(auth.require_user)):
    r = _render_for(render_id, user)
    p = Path(r["thumb_path"])
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg")


@app.get("/files/media/{media_id}")
def media_file(media_id: int, user=Depends(auth.require_admin)):
    m = db.q1("SELECT * FROM media WHERE id=?", (media_id,))
    if not m or not m["path"] or not Path(m["path"]).exists():
        raise HTTPException(404)
    return FileResponse(m["path"])


# ================= 관리자 =================

@app.get("/api/admin/dashboard")
def dashboard(user=Depends(auth.require_admin)):
    counts = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM orders GROUP BY status")}
    jobs = {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    month_rev = db.q1("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE status='paid' AND "
                      "created_at >= date('now','start of month')")["s"]
    cost_rows = db.q("SELECT cost_json FROM renders WHERE created_at >= date('now','start of month')")
    month_cost = round(sum(db.jload(r["cost_json"]).get("total_krw", 0) for r in cost_rows), 1)
    return {
        "orders": counts, "jobs": jobs, "month_revenue": month_rev, "month_cost_krw": month_cost,
        "month_ai_krw": costs.month_ai_spend_krw(), "month_renders": len(cost_rows),
        "customers": db.q1("SELECT COUNT(*) n FROM users WHERE role='customer'")["n"],
        "references": db.q1("SELECT COUNT(*) n FROM references_db WHERE active=1")["n"],
        "references_pending": db.q1("SELECT COUNT(*) n FROM references_db WHERE active=0")["n"],
    }


@app.get("/api/admin/orders")
def admin_orders(status: str = "", user=Depends(auth.require_admin)):
    sql = ("SELECT o.*, b.name biz_name, b.industry, u.name customer_name, u.phone customer_phone, u.email "
           "FROM orders o JOIN businesses b ON b.id=o.business_id JOIN users u ON u.id=o.user_id")
    args = ()
    if status:
        sql += " WHERE o.status=?"
        args = (status,)
    rows = db.q(sql + " ORDER BY o.id DESC LIMIT 200", args)
    for r in rows:
        r["job"] = db.q1("SELECT id,status,progress,step FROM jobs WHERE type='produce' AND "
                         "json_extract(payload_json,'$.order_id')=? ORDER BY id DESC LIMIT 1", (r["id"],))
        r["render_count"] = db.q1("SELECT COUNT(*) n FROM renders WHERE order_id=?", (r["id"],))["n"]
    return rows


@app.get("/api/admin/orders/{order_id}")
def admin_order(order_id: int, user=Depends(auth.require_admin)):
    o = db.q1("SELECT * FROM orders WHERE id=?", (order_id,))
    if not o:
        raise HTTPException(404)
    v = _order_view(o, admin=True)
    v["customer"] = db.q1("SELECT id,email,name,phone FROM users WHERE id=?", (o["user_id"],))
    v["payments"] = db.q("SELECT * FROM payments WHERE order_id=?", (order_id,))
    return v


@app.post("/api/admin/orders")
async def admin_create_order(request: Request, files: list[UploadFile] = File(...),
                             logo: UploadFile | None = File(None), user=Depends(auth.require_admin)):
    """카카오톡 등으로 받은 고객 영상을 관리자가 대신 접수."""
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    cname = form.get("customer_name", "").strip() or form.get("biz_name", "").strip()
    cphone = re.sub(r"[^0-9]", "", form.get("customer_phone", ""))
    email = form.get("customer_email", "").strip().lower() or f"{cphone or secrets.token_hex(4)}@customer.local"
    cu = db.q1("SELECT id FROM users WHERE email=?", (email,))
    if cu:
        uid = cu["id"]
    else:
        uid = db.run("INSERT INTO users(email,password_hash,name,phone,created_at) VALUES (?,?,?,?,?)",
                     (email, auth.hash_password(secrets.token_urlsafe(12)), cname, cphone, db.now()))
    return await _create_order(uid, form, files, logo, auto_start=form.get("auto_start", "1") == "1")


@app.post("/api/admin/orders/{order_id}/produce")
def admin_produce(order_id: int, style: str = Form("trend"), duration: int = Form(30), variants: int = Form(1),
                  hook_text: str = Form(""), user=Depends(auth.require_admin)):
    if not db.q1("SELECT id FROM orders WHERE id=?", (order_id,)):
        raise HTTPException(404)
    if duration not in config.ALLOWED_DURATIONS:
        raise HTTPException(400, "영상 길이는 15/30/45/60초 중 선택")
    styles = [style]
    if variants >= 3:  # 동일 원본으로 서로 다른 3가지 스타일
        pool = [s for s in ("trend", "emotional", "visit", "premium", "fast") if s != style]
        styles = [style, *pool[:2]]
    jobs = [_enqueue_produce(order_id, {"style": s, "duration": duration, "hook_text": hook_text}) for s in styles]
    return {"jobs": jobs}


@app.post("/api/admin/renders/{render_id}/rerender")
async def admin_rerender(render_id: int, request: Request, user=Depends(auth.require_admin)):
    """문구·자막·길이 수정 후 다시 렌더링(이전 버전은 그대로 보존)."""
    r = db.q1("SELECT * FROM renders WHERE id=?", (render_id,))
    if not r:
        raise HTTPException(404)
    body = await request.json()
    plan = db.jload(r["plan_json"])
    for k in ("hook_text", "cta_text", "title"):
        if k in body:
            plan[k] = str(body[k])[:100]
    if "captions" in body and isinstance(body["captions"], list):
        for s, c in zip(plan["scenes"][1:], body["captions"]):
            s["caption"] = str(c)[:60]
    if "caption_size" in body:
        plan["caption_style"]["size"] = int(max(40, min(130, int(body["caption_size"]))))
    if "caption_pos" in body and body["caption_pos"] in ("top", "middle", "bottom"):
        plan["caption_style"]["pos"] = body["caption_pos"]
    if body.get("brightness"):
        plan["color"][0] = round(plan["color"][0] + float(body["brightness"]), 3)
    if "end_card" in body and isinstance(body["end_card"], dict):
        for k in ("name", "address", "phone", "website"):
            if k in body["end_card"]:
                plan["end_card"][k] = str(body["end_card"][k])[:120]
    if body.get("duration") and int(body["duration"]) in config.ALLOWED_DURATIONS and int(body["duration"]) != plan["duration"]:
        plan = planner.retime(plan, int(body["duration"]))
    plan["notes"] = plan.get("notes", []) + [f"v{r['version']}에서 관리자 수정"]
    job = _enqueue_produce(r["order_id"], {"plan": plan})
    return {"job": job}


@app.post("/api/admin/renders/{render_id}/approve")
def admin_approve(render_id: int, user=Depends(auth.require_admin)):
    r = db.q1("SELECT * FROM renders WHERE id=?", (render_id,))
    if not r:
        raise HTTPException(404)
    db.run("UPDATE renders SET approved=1 WHERE id=?", (render_id,))
    db.run("UPDATE orders SET status='delivered', updated_at=? WHERE id=?", (db.now(), r["order_id"]))
    db.run("UPDATE revisions SET status='done' WHERE order_id=? AND status='open'", (r["order_id"],))
    return {"ok": True}


@app.post("/api/admin/orders/{order_id}/status")
def admin_set_status(order_id: int, status: str = Form(...), user=Depends(auth.require_admin)):
    if status not in ("received", "processing", "review", "delivered", "revision", "failed", "canceled"):
        raise HTTPException(400)
    db.run("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, db.now(), order_id))
    return {"ok": True}


@app.post("/api/admin/payments")
def admin_payment(order_id: int = Form(...), amount: int = Form(...), method: str = Form("manual"),
                  memo: str = Form(""), user=Depends(auth.require_admin)):
    o = db.q1("SELECT * FROM orders WHERE id=?", (order_id,))
    if not o:
        raise HTTPException(404)
    db.run("INSERT INTO payments(order_id,user_id,amount,method,memo,created_at) VALUES (?,?,?,?,?,?)",
           (order_id, o["user_id"], amount, method, memo, db.now()))
    db.run("UPDATE orders SET paid=1 WHERE id=?", (order_id,))
    return {"ok": True}


@app.get("/api/admin/payments")
def admin_payments(user=Depends(auth.require_admin)):
    return db.q("SELECT p.*, b.name biz_name FROM payments p LEFT JOIN orders o ON o.id=p.order_id "
                "LEFT JOIN businesses b ON b.id=o.business_id ORDER BY p.id DESC LIMIT 300")


@app.get("/api/admin/customers")
def admin_customers(user=Depends(auth.require_admin)):
    rows = db.q("SELECT id,email,name,phone,created_at FROM users WHERE role='customer' ORDER BY id DESC")
    for u in rows:
        u["orders"] = db.q1("SELECT COUNT(*) n FROM orders WHERE user_id=?", (u["id"],))["n"]
        u["revenue"] = db.q1("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE user_id=?", (u["id"],))["s"]
        cost = 0.0
        for r in db.q("SELECT r.cost_json FROM renders r JOIN orders o ON o.id=r.order_id WHERE o.user_id=?", (u["id"],)):
            cost += db.jload(r["cost_json"]).get("total_krw", 0)
        u["cost"] = round(cost, 1)
        u["profit"] = round(u["revenue"] - cost, 1)
    return rows


# ---- 작업(대기열) ----

@app.get("/api/admin/jobs")
def admin_jobs(user=Depends(auth.require_admin)):
    rows = db.q("SELECT id,type,status,progress,step,attempts,error,created_at,started_at,finished_at,payload_json "
                "FROM jobs ORDER BY id DESC LIMIT 100")
    for r in rows:
        p = db.jload(r.pop("payload_json"))
        r["order_id"] = p.get("order_id")
        r["style"] = p.get("style") or (p.get("plan") or {}).get("style")
        r["estimate"] = p.get("estimate")
    return rows


@app.post("/api/admin/jobs/{job_id}/retry")
def admin_retry(job_id: int, user=Depends(auth.require_admin)):
    db.run("UPDATE jobs SET status='queued', attempts=0, error='', progress=0, step='' WHERE id=? "
           "AND status IN ('failed','awaiting_approval')", (job_id,))
    return {"ok": True}


@app.post("/api/admin/jobs/{job_id}/cancel")
def admin_cancel(job_id: int, user=Depends(auth.require_admin)):
    db.run("UPDATE jobs SET status='failed', error='관리자 취소' WHERE id=? AND status IN ('queued','awaiting_approval')",
           (job_id,))
    return {"ok": True}


# ---- 벤치마킹(참고 영상/패턴) ----

REF_FIELDS = ("industry", "platform", "url", "title", "hook_type", "hook_text", "edit_pattern", "caption_style",
              "caption_position", "music_mood", "story_structure", "cta_type", "notes", "ai_summary",
              "template_style")


@app.get("/api/admin/references")
def admin_refs(industry: str = "", user=Depends(auth.require_admin)):
    sql, args = "SELECT * FROM references_db", ()
    if industry:
        sql, args = sql + " WHERE industry=?", (industry,)
    rows = db.q(sql + " ORDER BY id DESC", args)
    for r in rows:
        r["metrics"] = db.jload(r.pop("metrics_json"))
    return rows


@app.get("/api/admin/patterns/{industry}")
def admin_pattern(industry: str, user=Depends(auth.require_admin)):
    return benchmark.industry_pattern(industry)


def _manual_metrics(form: dict) -> dict:
    m = {}
    for k in ("views", "likes", "comments", "shares", "channel_subscribers"):
        v = re.sub(r"[^0-9]", "", form.get(k, "") or "")
        if v:
            m[k] = int(v)
    if form.get("published_at"):
        m["published_at"] = form["published_at"]
    if m:
        m["source"] = "manual"
    return m


@app.post("/api/admin/references")
async def admin_ref_create(request: Request, user=Depends(auth.require_admin)):
    form_data = await request.form()
    form = {k: v for k, v in form_data.items() if isinstance(v, str)}
    video = form_data.get("video")
    if form.get("industry") not in INDUSTRIES:
        raise HTTPException(400, "업종을 선택해 주세요.")
    vals = {k: form.get(k, "").strip() for k in REF_FIELDS}
    if not vals["platform"]:
        vals["platform"] = benchmark.detect_platform(vals["url"])
    metrics = {"manual": _manual_metrics(form)} if _manual_metrics(form) else {}
    warn = ""
    if vals["platform"] == "youtube" and vals["url"] and config.YOUTUBE_API_KEY:
        try:
            yt = benchmark.fetch_youtube(vals["url"])
            metrics.update(yt["metrics"])
            vals["title"] = vals["title"] or yt["title"]
        except Exception as e:
            warn = f"유튜브 API 조회 실패: {e}"
    rid = db.run(
        f"INSERT INTO references_db({','.join(REF_FIELDS)},metrics_json,created_at) VALUES ({','.join('?' * len(REF_FIELDS))},?,?)",
        (*[vals[k] for k in REF_FIELDS], db.jdump(metrics), db.now()))
    if metrics.get("duration_iso"):
        db.run("UPDATE references_db SET duration_sec=? WHERE id=?", (benchmark.iso_duration_sec(metrics["duration_iso"]), rid))
    job = None
    if isinstance(video, UploadFile) and video.filename:
        path, _, kind = await _save_upload(video, config.REFERENCE_DIR)
        if kind != "video":
            raise HTTPException(400, "참고 영상은 동영상 파일이어야 합니다.")
        db.run("UPDATE references_db SET video_path=? WHERE id=?", (path, rid))
        job = _enqueue("analyze_reference", {"ref_id": rid, "path": path})
    ref = db.q1("SELECT * FROM references_db WHERE id=?", (rid,))
    db.run("UPDATE references_db SET reliability=? WHERE id=?", (benchmark.compute_reliability(ref), rid))
    return {"id": rid, "job_id": job, "warning": warn}


@app.put("/api/admin/references/{ref_id}")
async def admin_ref_update(ref_id: int, request: Request, user=Depends(auth.require_admin)):
    body = await request.json()
    ref = db.q1("SELECT * FROM references_db WHERE id=?", (ref_id,))
    if not ref:
        raise HTTPException(404)
    sets, args = [], []
    for k in (*REF_FIELDS, "active"):
        if k in body:
            sets.append(f"{k}=?")
            args.append(int(bool(body[k])) if k == "active" else str(body[k]).strip())
    for k in ("avg_cut_sec", "duration_sec"):
        if body.get(k) not in (None, ""):
            sets.append(f"{k}=?")
            args.append(float(body[k]))
    if "metrics" in body and isinstance(body["metrics"], dict):
        m = db.jload(ref["metrics_json"])
        manual = _manual_metrics({k: str(v) for k, v in body["metrics"].items()})
        if manual:
            m["manual"] = manual
        sets.append("metrics_json=?")
        args.append(db.jdump(m))
    if sets:
        db.run(f"UPDATE references_db SET {','.join(sets)} WHERE id=?", (*args, ref_id))
    ref = db.q1("SELECT * FROM references_db WHERE id=?", (ref_id,))
    db.run("UPDATE references_db SET reliability=? WHERE id=?", (benchmark.compute_reliability(ref), ref_id))
    return {"ok": True}


@app.delete("/api/admin/references/{ref_id}")
def admin_ref_delete(ref_id: int, user=Depends(auth.require_admin)):
    ref = db.q1("SELECT video_path FROM references_db WHERE id=?", (ref_id,))
    if ref and ref["video_path"]:
        Path(ref["video_path"]).unlink(missing_ok=True)
    db.run("DELETE FROM references_db WHERE id=?", (ref_id,))
    return {"ok": True}


# ---- 배경음악(상업적 이용 허용 음원만) ----

@app.get("/api/admin/music")
def admin_music(user=Depends(auth.require_admin)):
    return db.q("SELECT * FROM music ORDER BY id DESC")


@app.post("/api/admin/music")
async def admin_music_add(file: UploadFile = File(...), title: str = Form(...), mood: str = Form(""),
                          bpm: str = Form(""), license_source: str = Form(...), license_terms: str = Form(...),
                          commercial_ok: str = Form("0"), user=Depends(auth.require_admin)):
    if commercial_ok != "1":
        raise HTTPException(400, "상업적 이용이 허용된 음원만 등록할 수 있습니다. 라이선스를 확인해 주세요.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp3", ".m4a", ".wav", ".aac", ".ogg"}:
        raise HTTPException(400, "음원 파일(mp3, m4a, wav, aac, ogg)만 가능합니다.")
    dest = config.MUSIC_DIR / f"{uuid.uuid4().hex}{ext}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    from .services.ffmpeg_util import probe
    try:
        dur = probe(dest)["duration"]
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "음원 파일을 읽을 수 없습니다.")
    bpm_v = float(bpm) if re.match(r"^\d+(\.\d+)?$", bpm.strip()) else None
    mid = db.run("INSERT INTO music(title,mood,path,bpm,duration_sec,license_source,license_terms,commercial_ok,created_at)"
                 " VALUES (?,?,?,?,?,?,?,1,?)", (title, mood, str(dest), bpm_v, dur, license_source, license_terms, db.now()))
    return {"id": mid}


@app.post("/api/admin/music/{music_id}/toggle")
def admin_music_toggle(music_id: int, user=Depends(auth.require_admin)):
    db.run("UPDATE music SET active=1-active WHERE id=?", (music_id,))
    return {"ok": True}


# ---- 상품/가격, 설정, 시스템 상태 ----

@app.get("/api/admin/products")
def admin_products(user=Depends(auth.require_admin)):
    return db.q("SELECT * FROM products ORDER BY sort")


@app.put("/api/admin/products/{code}")
async def admin_product_update(code: str, request: Request, user=Depends(auth.require_admin)):
    body = await request.json()
    if "price" in body:
        db.run("UPDATE products SET price=? WHERE code=?", (max(0, int(body["price"])), code))
    if "name" in body:
        db.run("UPDATE products SET name=? WHERE code=?", (str(body["name"])[:60], code))
    if "active" in body:
        db.run("UPDATE products SET active=? WHERE code=?", (int(bool(body["active"])), code))
    return {"ok": True}


@app.get("/api/admin/settings")
def admin_settings(user=Depends(auth.require_admin)):
    return {r["key"]: r["value"] for r in db.q("SELECT * FROM settings")}


@app.put("/api/admin/settings")
async def admin_settings_update(request: Request, user=Depends(auth.require_admin)):
    body = await request.json()
    for k, v in body.items():
        if k in db.DEFAULT_SETTINGS:
            if not re.match(r"^\d+(\.\d+)?$", str(v)):
                raise HTTPException(400, f"{k}: 숫자만 입력해 주세요.")
            db.run("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (k, str(v)))
    return {"ok": True}


@app.get("/api/admin/system")
def admin_system(user=Depends(auth.require_admin)):
    import shutil as sh
    from .services.ffmpeg_util import run as ffrun
    du = sh.disk_usage(config.DATA_DIR)
    try:
        ffv = ffrun(["ffmpeg", "-version"]).splitlines()[0]
    except Exception as e:
        ffv = f"오류: {e}"
    worker_alive = db.q1("SELECT MAX(COALESCE(finished_at, started_at)) t FROM jobs")
    return {
        "version": __version__, "env": config.APP_ENV, "ffmpeg": ffv,
        "disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1),
        "integrations": {
            "claude": {"configured": bool(config.ANTHROPIC_API_KEY), "model": config.CLAUDE_MODEL,
                       "desc": "AI 장면 인식·홍보 문구(유료, 선택)"},
            "youtube": {"configured": bool(config.YOUTUBE_API_KEY), "desc": "유튜브 조회수 등 공식 데이터(무료 할당량)"},
            "telegram": {"configured": bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID),
                         "desc": "운영자 스마트폰 알림(무료)"},
            "whisper": {"configured": bool(config.WHISPER_MODEL), "model": config.WHISPER_MODEL,
                        "error": None if db.setting("asr_status", "").startswith("정상") else db.setting("asr_status", "") or None,
                        "desc": "음성 인식 자막(무료, 서버 실행) — 상태: " + (db.setting("asr_status", "") or "아직 사용 기록 없음")},
            "payment": {"configured": False, "desc": "카드 결제 연동 전(현재 수동 입금 확인)"},
        },
        "last_job_activity": worker_alive["t"] if worker_alive else None,
        "font": config.FONT_FILE, "font_exists": Path(config.FONT_FILE).exists(),
    }


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    if exc.status_code == 401 and not request.url.path.startswith(("/api", "/files")):
        return RedirectResponse("/")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

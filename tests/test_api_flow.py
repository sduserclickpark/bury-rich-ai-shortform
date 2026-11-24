"""실제 업로드 → 작업 처리 → MP4 생성 → 검수 승인 → 고객 다운로드까지 전체 흐름 테스트."""
from fastapi.testclient import TestClient

from app import db, worker
from app.main import app
from app.services.ffmpeg_util import probe


def test_full_flow(media_dir):
    with TestClient(app) as cust, TestClient(app) as adm:
        r = cust.post("/api/signup", data={"email": "c@test.kr", "password": "12345678", "name": "고객"})
        assert r.status_code == 200
        with open(media_dir / "clip.mp4", "rb") as v, open(media_dir / "photo.jpg", "rb") as ph:
            r = cust.post("/api/orders", data={
                "biz_name": "테스트 식당", "industry": "restaurant", "address": "서울 마포구 망원동",
                "products": "김밥, 라면", "purpose": "visit", "style": "trend", "duration": "15",
                "product_code": "free_trial"},
                files=[("files", ("clip.mp4", v, "video/mp4")), ("files", ("photo.jpg", ph, "image/jpeg"))])
        assert r.status_code == 200, r.text
        oid = r.json()["order_id"]
        # 무료 체험 2회 불가
        r2 = cust.post("/api/orders", data={"biz_name": "x", "industry": "cafe", "product_code": "free_trial"},
                       files=[("files", ("a.jpg", open(media_dir / "photo.jpg", "rb"), "image/jpeg"))])
        assert r2.status_code == 400

        job = worker.claim()
        assert job and job["type"] == "produce"
        worker.process(job)
        j = db.q1("SELECT * FROM jobs WHERE id=?", (job["id"],))
        assert j["status"] == "done", j["error"] + j["log"]

        rend = db.q1("SELECT * FROM renders WHERE order_id=?", (oid,))
        info = probe(rend["output_path"])
        assert (info["width"], info["height"]) == (1080, 1920)
        assert abs(info["duration"] - 15) < 0.2 and info["has_audio"]

        # 승인 전 고객은 볼 수 없음
        assert cust.get(f"/files/render/{rend['id']}.mp4").status_code == 404
        assert cust.get("/api/admin/orders").status_code == 403

        assert adm.post("/api/login", data={"email": "admin@test.local", "password": "admin-pass-123"}).status_code == 200
        assert adm.post(f"/api/admin/renders/{rend['id']}/approve").status_code == 200
        r = cust.get(f"/files/render/{rend['id']}.mp4")
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        o = cust.get(f"/api/orders/{oid}").json()
        assert o["status"] == "delivered" and o["renders"][0]["sns"]["instagram"]

        # 관리자 수정 → 새 버전, 이전 버전 보존
        r = adm.post(f"/api/admin/renders/{rend['id']}/rerender", json={"hook_text": "새 후킹 문구", "caption_size": 100})
        assert r.status_code == 200
        job = worker.claim()
        worker.process(job)
        rows = db.q("SELECT version FROM renders WHERE order_id=? ORDER BY version", (oid,))
        assert [x["version"] for x in rows] == [1, 2]

        # 벤치마킹 자료 등록(수동 입력)
        r = adm.post("/api/admin/references", data={"industry": "restaurant", "url": "https://www.instagram.com/reel/x",
                                                    "views": "12,000", "hook_type": "음식 클로즈업", "template_style": "food"})
        assert r.status_code == 200
        refs = adm.get("/api/admin/references").json()
        mine = [x for x in refs if x["platform"] == "instagram"][0]
        assert mine["metrics"]["manual"]["views"] == 12000 and mine["metrics"]["manual"]["source"] == "manual"

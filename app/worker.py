"""백그라운드 작업 처리기(워커).

웹 서버와 별도 프로세스로 실행되며, 스마트폰 화면을 끄거나 개발 세션이 끝나도 서버에서 계속 동작한다.
- 작업 대기열(jobs 테이블)을 확인해 하나씩 처리
- 실패 시 자동 재시도(최대 MAX_JOB_ATTEMPTS)
- 매일 데이터베이스 백업, 보관 기간이 지난 원본 정리
실행: python -m app.worker
"""
from __future__ import annotations

import logging
import signal
import sqlite3
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, db
from .services import benchmark, notify, pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(levelname)s %(message)s")
log = logging.getLogger("worker")
_stop = False


def _sig(*_):
    global _stop
    _stop = True


def claim() -> dict | None:
    return db.q1(
        "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1, error='' "
        "WHERE id=(SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) RETURNING *",
        (db.now(),),
    )


def process(job: dict) -> None:
    jid = job["id"]
    payload = db.jload(job["payload_json"])

    def progress(pct: int, step: str):
        db.run("UPDATE jobs SET progress=?, step=? WHERE id=?", (int(pct), step, jid))

    try:
        if job["type"] == "produce":
            res = pipeline.produce(jid, payload, progress)
            order = db.q1("SELECT o.id, b.name FROM orders o JOIN businesses b ON b.id=o.business_id WHERE o.id=?",
                          (payload["order_id"],))
            notify.admin(f"영상 완성 — 주문 #{order['id']} {order['name']} (v{res['version']}). 검수해 주세요.")
        elif job["type"] == "analyze_reference":
            res = benchmark.analyze_reference_video(payload["ref_id"], payload["path"])
        else:
            raise ValueError(f"알 수 없는 작업 종류: {job['type']}")
        db.run("UPDATE jobs SET status='done', progress=100, step='완료', finished_at=?, log=? WHERE id=?",
               (db.now(), db.jdump(res)[:4000], jid))
        log.info("job %s done", jid)
    except Exception as e:
        tb = traceback.format_exc()
        log.error("job %s failed: %s", jid, e)
        final = job["attempts"] >= config.MAX_JOB_ATTEMPTS
        db.run("UPDATE jobs SET status=?, error=?, log=?, finished_at=? WHERE id=?",
               ("failed" if final else "queued", str(e)[:2000], tb[-4000:], db.now(), jid))
        if final:
            if job["type"] == "produce":
                db.run("UPDATE orders SET status='failed', updated_at=? WHERE id=?", (db.now(), payload["order_id"]))
            notify.admin(f"작업 실패 #{jid} ({job['type']}): {str(e)[:200]}")


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = config.BACKUP_DIR / f"studio_{stamp}.db"
    src = db.connect()
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close()
    src.close()
    backups = sorted(config.BACKUP_DIR.glob("studio_*.db"))
    for old in backups[:-14]:
        old.unlink(missing_ok=True)
    return dest


def cleanup_retention() -> int:
    """보관 기간이 지난 '전달 완료' 주문의 원본 파일 삭제(완성본은 유지)."""
    days = int(db.setting("retention_days", str(config.RETENTION_DAYS)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.q("SELECT m.id, m.path FROM media m JOIN orders o ON o.id=m.order_id "
                "WHERE o.status='delivered' AND o.updated_at < ? AND m.path != ''", (cutoff,))
    for r in rows:
        Path(r["path"]).unlink(missing_ok=True)
        db.run("UPDATE media SET path='' WHERE id=?", (r["id"],))
    return len(rows)


def main() -> None:
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    db.init()
    # 이전에 비정상 종료된 작업은 다시 대기열로
    db.run("UPDATE jobs SET status='queued' WHERE status='running'")
    log.info("worker started (data=%s)", config.DATA_DIR)
    last_maint = 0.0
    while not _stop:
        if time.time() - last_maint > 24 * 3600:
            try:
                log.info("backup: %s, retention cleanup: %d", backup_db(), cleanup_retention())
            except Exception as e:
                log.warning("maintenance failed: %s", e)
            last_maint = time.time()
        job = claim()
        if job:
            process(job)
        else:
            time.sleep(config.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    main()

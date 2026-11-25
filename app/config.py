"""환경설정. 모든 비밀값(API 키 등)은 서버 환경변수로만 관리한다."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
WORK_DIR = DATA_DIR / "work"
MUSIC_DIR = DATA_DIR / "music"
REFERENCE_DIR = DATA_DIR / "references"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "studio.db")))

APP_ENV = _env("APP_ENV", "development")  # development | production
SECRET_KEY = _env("SECRET_KEY", "dev-secret-change-me")
ADMIN_EMAIL = _env("ADMIN_EMAIL", "admin@buryrich.local")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "")

# 외부 API (선택). 값이 없으면 해당 기능은 무료 대체 방식으로 동작하거나 비활성화된다.
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-opus-5-5")
YOUTUBE_API_KEY = _env("YOUTUBE_API_KEY")
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

# 음성 인식(무료, 서버 CPU에서 실행). tiny/base/small/medium. 비우면 음성인식 끔.
WHISPER_MODEL = _env("WHISPER_MODEL", "small")

FONT_FILE = _env("FONT_FILE", "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf")
FONT_NAME = _env("FONT_NAME", "NanumSquareRound")
FONT_DIR = str(Path(FONT_FILE).parent)

MAX_UPLOAD_MB = int(_env("MAX_UPLOAD_MB", "1024"))
WORKER_POLL_SECONDS = float(_env("WORKER_POLL_SECONDS", "3"))
MAX_JOB_ATTEMPTS = int(_env("MAX_JOB_ATTEMPTS", "3"))
RETENTION_DAYS = int(_env("RETENTION_DAYS", "90"))

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30
ALLOWED_DURATIONS = (15, 30, 45, 60)
USD_KRW = float(_env("USD_KRW", "1400"))



def production_problems() -> list[str]:
    """운영(production) 모드에서 반드시 고쳐야 하는 설정 문제 목록."""
    probs = []
    if APP_ENV == "production":
        if SECRET_KEY in ("", "dev-secret-change-me") or len(SECRET_KEY) < 32:
            probs.append("SECRET_KEY 환경변수를 32자 이상의 임의 문자열로 설정해야 합니다.")
        if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 8:
            probs.append("ADMIN_PASSWORD 환경변수를 8자 이상으로 설정해야 합니다.")
    return probs


for d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR, WORK_DIR, MUSIC_DIR, REFERENCE_DIR, BACKUP_DIR):
    d.mkdir(parents=True, exist_ok=True)

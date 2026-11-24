"""비밀번호 해시 및 로그인 세션."""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from . import db

ITER = 240_000


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), ITER).hex()
    return f"pbkdf2${ITER}${salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except ValueError:
        return False


def current_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    return db.q1("SELECT id,email,name,phone,role,free_trial_used FROM users WHERE id=?", (uid,))


def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "로그인이 필요합니다.")
    return u


def require_admin(request: Request) -> dict:
    u = require_user(request)
    if u["role"] != "admin":
        raise HTTPException(403, "관리자만 사용할 수 있습니다.")
    return u


def ensure_admin(email: str, password: str) -> None:
    if not password:
        return
    if not db.q1("SELECT id FROM users WHERE email=?", (email,)):
        db.run("INSERT INTO users(email,password_hash,name,role,created_at) VALUES (?,?,?,?,?)",
               (email, hash_password(password), "관리자", "admin", db.now()))

"""간단한 로컬 사용자 인증 + 사용자별 데이터 폴더 관리.
로컬 대시보드용 경량 인증입니다(비밀번호는 PBKDF2로 해시 저장).
"""
import os
import json
import hashlib
import hmac
import base64
import re

BASE_DIR = os.path.join(os.path.dirname(__file__), "user_data")
USERS_FILE = os.path.join(BASE_DIR, "users.json")


def _ensure_base():
    os.makedirs(BASE_DIR, exist_ok=True)


def _load_users():
    _ensure_base()
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users):
    _ensure_base()
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _hash_pw(password, salt):
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
    return base64.b64encode(dk).decode("ascii")


def _safe_username(username):
    """폴더명으로 안전한 사용자 ID (영숫자/._- 만 허용)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", username.strip())


def user_dir(username):
    """사용자별 데이터 폴더 경로(없으면 생성)."""
    d = os.path.join(BASE_DIR, _safe_username(username))
    os.makedirs(d, exist_ok=True)
    return d


def register_user(username, password):
    """신규 사용자 등록. 반환: (성공여부, 메시지)"""
    username = (username or "").strip()
    if not username or not password:
        return False, "아이디와 비밀번호를 입력하세요."
    if len(password) < 4:
        return False, "비밀번호는 4자 이상이어야 합니다."
    users = _load_users()
    if username in users:
        return False, "이미 존재하는 아이디입니다."
    salt = os.urandom(16)
    users[username] = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": _hash_pw(password, salt),
    }
    _save_users(users)
    user_dir(username)  # 폴더 생성
    return True, "회원가입 완료! 로그인하세요."


def verify_user(username, password):
    """로그인 검증. 반환: (성공여부, 메시지)"""
    username = (username or "").strip()
    users = _load_users()
    rec = users.get(username)
    if not rec:
        return False, "존재하지 않는 아이디입니다."
    salt = base64.b64decode(rec["salt"])
    if hmac.compare_digest(_hash_pw(password, salt), rec["hash"]):
        return True, "로그인 성공"
    return False, "비밀번호가 올바르지 않습니다."

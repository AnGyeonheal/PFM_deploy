"""간단한 로컬 사용자 인증 + 사용자별 데이터 폴더 관리.
로컬 대시보드용 경량 인증입니다(비밀번호는 PBKDF2로 해시 저장).
"""
import os
import json
import time
import shutil
import hashlib
import hmac
import base64
import re
import secrets
from datetime import datetime, timezone

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


def delete_user(username, wipe_data=True):
    """단일 계정 삭제 + (옵션) 사용자 데이터 폴더 제거. 반환: 존재했는지 여부."""
    users = _load_users()
    existed = username in users
    if existed:
        users.pop(username, None)
        _save_users(users)
    if wipe_data:
        d = os.path.join(BASE_DIR, _safe_username(username))
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return existed


def delete_all_users(wipe_data=True):
    """모든 계정을 삭제(users.json 비움)하고 모든 로그인 세션을 무효화합니다.
    wipe_data=True면 각 사용자 데이터 폴더도 제거합니다. 반환: (삭제 계정 수, 삭제 폴더 수)."""
    users = _load_users()
    n_users = len(users)
    n_dirs = 0
    if wipe_data and os.path.isdir(BASE_DIR):
        for name in os.listdir(BASE_DIR):
            p = os.path.join(BASE_DIR, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                n_dirs += 1
    _save_users({})
    _save_sessions({})  # 모든 로그인 세션 토큰 무효화
    return n_users, n_dirs


def _hash_pw(password, salt):
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
    return base64.b64encode(dk).decode("ascii")


def _now_iso():
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


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
        "created_at": _now_iso(),
        "last_login": None,
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
        rec["last_login"] = _now_iso()
        rec.setdefault("created_at", rec["last_login"])
        users[username] = rec
        _save_users(users)
        return True, "로그인 성공"
    return False, "비밀번호가 올바르지 않습니다."


# ───────────────────────── 사용자별 API 자격 증명 ─────────────────────────
# 토스/Gemini API 키를 사용자 폴더(user_data/<user>/credentials.json)에 로컬 저장합니다.
# user_data/ 는 .gitignore 로 제외되어 커밋되지 않습니다.
CRED_KEYS = ("TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET", "TOSS_ACCOUNT_NO", "GEMINI_API_KEY")


def _cred_path(username):
    return os.path.join(user_dir(username), "credentials.json")


def load_credentials(username):
    """사용자별 저장된 API 자격 증명 dict를 반환합니다(없으면 빈 dict)."""
    path = _cred_path(username)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_credentials(username, creds):
    """전달된 자격 증명을 저장합니다. 값이 비어 있는 키는 기존 값을 유지(갱신하지 않음)합니다.
    반환: 저장된(비어있지 않은) 키 개수."""
    data = load_credentials(username)
    saved = 0
    for k in CRED_KEYS:
        v = creds.get(k)
        v = v.strip() if isinstance(v, str) else v
        if v:
            data[k] = str(v)
            saved += 1
    with open(_cred_path(username), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return saved


def has_toss_credentials(username):
    """토스 API 키(CLIENT_ID·SECRET)가 저장되어 있는지 여부."""
    c = load_credentials(username)
    return bool(c.get("TOSS_CLIENT_ID") and c.get("TOSS_CLIENT_SECRET"))


# ───────────────────────── 사용자 프로필 조회 ─────────────────────────
def get_user_info(username):
    """사용자 메타데이터(가입일·마지막 로그인)를 반환합니다. 비밀번호/해시는 제외."""
    username = (username or "").strip()
    rec = _load_users().get(username)
    if not rec:
        return {}
    return {
        "username": username,
        "created_at": rec.get("created_at"),
        "last_login": rec.get("last_login"),
    }


# ───────────────────────── 세션 유지(자동 로그인) ─────────────────────────
# 새로고침·앱 재시작에도 로그인을 유지하기 위한 서버측 세션 토큰 저장소입니다.
# URL 쿼리에는 임의 토큰만 노출되고(아이디/비밀번호 아님), 만료 시 자동 폐기됩니다.
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
SESSION_TTL_DAYS = 30


def _load_sessions():
    _ensure_base()
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_sessions(sessions):
    _ensure_base()
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def _prune_sessions(sessions):
    """만료된 세션 토큰을 제거합니다. 제거 여부를 반환."""
    now = time.time()
    expired = [t for t, r in sessions.items() if r.get("expires_at", 0) < now]
    for t in expired:
        sessions.pop(t, None)
    return bool(expired)


def create_session(username):
    """로그인 성공 시 호출. 임의 세션 토큰을 발급·저장하고 토큰 문자열을 반환합니다."""
    username = (username or "").strip()
    if not username:
        return None
    token = secrets.token_urlsafe(32)
    sessions = _load_sessions()
    _prune_sessions(sessions)
    sessions[token] = {
        "username": username,
        "expires_at": time.time() + SESSION_TTL_DAYS * 86400,
    }
    _save_sessions(sessions)
    return token


def resolve_session(token):
    """유효한 세션 토큰이면 username을, 아니면 None을 반환합니다(만료·삭제된 사용자 토큰은 폐기)."""
    if not token:
        return None
    sessions = _load_sessions()
    rec = sessions.get(token)
    if not rec:
        return None
    if rec.get("expires_at", 0) < time.time() or (rec.get("username") or "") not in _load_users():
        sessions.pop(token, None)
        _save_sessions(sessions)
        return None
    return rec.get("username")


def destroy_session(token):
    """로그아웃 시 세션 토큰을 폐기합니다."""
    if not token:
        return
    sessions = _load_sessions()
    changed = _prune_sessions(sessions)
    if token in sessions:
        sessions.pop(token, None)
        changed = True
    if changed:
        _save_sessions(sessions)

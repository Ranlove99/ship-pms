"""密码哈希与角色权限。"""
import hashlib
import hmac
import os

ITERATIONS = 120_000
ROLE_LABEL = {
    "admin": "系统管理员",
    "master": "船长",
    "chief": "轮机长",
    "officer": "轮机员/驾驶员",
    "crew": "普通船员",
}


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("pbkdf2$"):
        return False
    try:
        _, iterations, salt, digest = stored.split("$", 3)
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(calc, digest)
    except (ValueError, TypeError):
        return False


# 权限矩阵：动作 → 允许的角色
PERMISSIONS = {
    "asset.write": {"admin", "chief"},
    "plan.write": {"admin", "chief"},
    "wo.write": {"admin", "chief", "master", "officer"},
    "wo.verify": {"admin", "chief", "master"},
    "defect.write": {"admin", "chief", "master", "officer", "crew"},
    "defect.close": {"admin", "chief", "master"},
    "part.write": {"admin", "chief"},
    "part.move": {"admin", "chief", "officer"},
    "cert.write": {"admin", "master", "chief"},
    "record.write": {"admin", "chief", "master"},
    "record.verify": {"admin", "master"},
    "report.view": {"admin", "chief", "master", "officer"},
    "user.manage": {"admin"},
    "system.manage": {"admin"},
}


def allowed(user: dict | None, action: str) -> bool:
    if not user:
        return False
    roles = PERMISSIONS.get(action, set())
    return user.get("role") in roles

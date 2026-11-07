"""运行配置：全部路径来自 fnOS 生命周期环境变量，禁止硬编码 /var/apps。"""
import os
import secrets

APP_NAME = "ship-pms"
APP_VERSION = os.environ.get("TRIM_APPVER") or "1.2.0"

_HERE = os.path.dirname(os.path.abspath(__file__))


def _env_path(key: str, fallback: str) -> str:
    value = os.environ.get(key, "").strip()
    return value if value else fallback


class Config:
    VERSION = APP_VERSION

    # fnOS 约定的目录（安装后为符号链接，指向用户选择的存储卷）
    APPDEST = _env_path("TRIM_APPDEST", f"/var/apps/{APP_NAME}/target")
    PKGVAR = _env_path("TRIM_PKGVAR", f"/var/apps/{APP_NAME}/var")
    PKGETC = _env_path("TRIM_PKGETC", f"/var/apps/{APP_NAME}/etc")
    PKGTMP = _env_path("TRIM_PKGTMP", f"/var/apps/{APP_NAME}/tmp")
    DATA_SHARE = _env_path("TRIM_DATA_SHARE_PATHS", f"/var/apps/{APP_NAME}/share").split(":")[0]

    # 应用自身路径
    BASE_DIR = _HERE
    DB_PATH = os.path.join(_env_path("TRIM_PKGVAR", f"/var/apps/{APP_NAME}/var"), "data", "pms.db")
    ATTACH_DIR = os.path.join(_env_path("TRIM_PKGVAR", f"/var/apps/{APP_NAME}/var"), "attachments")
    BACKUP_DIR = os.path.join(_env_path("TRIM_PKGVAR", f"/var/apps/{APP_NAME}/var"), "backups")
    LOG_FILE = os.path.join(_env_path("TRIM_PKGVAR", f"/var/apps/{APP_NAME}/var"), "app.log")
    CONFIG_FILE = os.path.join(_env_path("TRIM_PKGETC", f"/var/apps/{APP_NAME}/etc"), "config.json")

    SOCKET_PATH = os.path.join(_env_path("TRIM_APPDEST", f"/var/apps/{APP_NAME}/target"), "app.sock")
    THREADS = int(os.environ.get("PMS_THREADS", "4"))
    MAX_UPLOAD_MB = 8
    SESSION_HOURS = 12

    @classmethod
    def ensure_dirs(cls) -> None:
        for path in (os.path.dirname(cls.DB_PATH), cls.ATTACH_DIR, cls.BACKUP_DIR):
            os.makedirs(path, exist_ok=True)

    @classmethod
    def secret_key(cls) -> str:
        """会话密钥持久化在 etc 目录，重启不失效。"""
        os.makedirs(os.path.dirname(cls.CONFIG_FILE), exist_ok=True)
        try:
            with open(cls.CONFIG_FILE, "r", encoding="utf-8") as fh:
                raw = fh.read().strip()
            if raw:
                import json
                return json.loads(raw).get("secret_key") or cls._write_secret()
        except (OSError, ValueError):
            pass
        return cls._write_secret()

    @classmethod
    def _write_secret(cls) -> str:
        import json
        key = secrets.token_hex(32)
        try:
            with open(cls.CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump({"secret_key": key}, fh)
        except OSError:
            pass
        return key

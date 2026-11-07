"""WSGI 入口：waitress + Unix socket（fnOS 统一网关要求 app.sock 位于 TRIM_APPDEST）。

本地调试：python wsgi.py --port 8080
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

from app import create_app  # noqa: E402
from config import Config  # noqa: E402

application = create_app()


def main() -> int:
    argv = sys.argv[1:]
    port = None
    for i, item in enumerate(argv):
        if item == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif item.startswith("--port="):
            port = int(item.split("=", 1)[1])

    import waitress

    if port:
        print(f"serving on http://127.0.0.1:{port}")
        waitress.serve(application, host="127.0.0.1", port=port, threads=Config.THREADS)
        return 0

    socket_path = Config.SOCKET_PATH
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)
    if os.path.exists(socket_path):
        try:
            os.unlink(socket_path)
        except OSError:
            pass
    print(f"serving on unix:{socket_path}")
    waitress.serve(
        application,
        unix_socket=socket_path,
        unix_socket_perms="660",
        threads=Config.THREADS,
        clear_untrusted_proxy_headers=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

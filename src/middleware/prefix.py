"""统一网关前缀处理。

fnOS 网关把 /app/<appname>/... 原样转发（不剥前缀）。这里统一剥离，
同时设置 SCRIPT_NAME，使 url_for 生成的链接自带前缀；无前缀直连同样可用。
"""


class PrefixMiddleware:
    def __init__(self, app, prefix: str = ""):
        self.app = app
        self.prefix = ("/" + prefix.strip("/")) if prefix.strip("/") else ""

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.app(environ, start_response)
        path = environ.get("PATH_INFO", "") or "/"
        prefix = self.prefix

        if path == prefix:
            environ["PATH_INFO"] = "/"
            environ["SCRIPT_NAME"] = prefix
        elif path.startswith(prefix + "/"):
            environ["PATH_INFO"] = path[len(prefix):]
            environ["SCRIPT_NAME"] = prefix
        else:
            # 不带前缀的直连（本机调试、健康检查）
            environ.setdefault("SCRIPT_NAME", "")
        return self.app(environ, start_response)

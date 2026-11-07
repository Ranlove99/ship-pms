#!/bin/bash
# ============================================================
# 构建 ship-pms.fpk
# 用法: bash scripts/build_fpk.sh [版本号]
# 前置: 可访问 static2.fnnas.com 下载 fnpack，或设置 FNPACK=/path/to/fnpack
#
# 目录约定：
#   packaging/    fpk 静态骨架（manifest / cmd / config / wizard / ui / 图标）
#   src/          应用源码
#   build/        构建产物（每次重建，不手改）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT/build/ship-pms"
PKG_SRC="$ROOT/packaging"
SRC_DIR="$ROOT/src"
APP_ROOT="$PKG_DIR/app"
VENDOR="$APP_ROOT/vendor"

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  VERSION="$(grep -E '^version' "$PKG_SRC/manifest" | head -1 | cut -d= -f2 | tr -d ' `"')"
fi
echo "==> 版本 $VERSION"

# ---------- 1. 图标 ----------
echo "==> 生成图标"
python3 "$ROOT/scripts/make_icons.py" >/dev/null

# ---------- 2. 重建打包目录（完全由 packaging/ 生成） ----------
echo "==> 装配打包骨架"
rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"
cp -R "$PKG_SRC/." "$PKG_DIR/"
find "$PKG_DIR" -name ".DS_Store" -delete 2>/dev/null || true
chmod +x "$PKG_DIR/cmd/"* 2>/dev/null || true

# ---------- 3. 同步源码 ----------
echo "==> 同步应用代码"
find "$SRC_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$SRC_DIR" -name "*.pyc" -delete 2>/dev/null || true
mkdir -p "$APP_ROOT" "$VENDOR"
cp -R "$SRC_DIR/." "$APP_ROOT/"

# ---------- 4. 安装纯 Python 依赖 ----------
echo "==> 安装依赖到 vendor"
pip3 install --quiet --no-compile --upgrade --target "$VENDOR" \
  flask waitress 2>&1 | tail -3 || { echo "依赖安装失败"; exit 1; }

find "$VENDOR" -name "*.so" -delete 2>/dev/null || true
find "$VENDOR" -name "*.pyd" -delete 2>/dev/null || true
find "$VENDOR" -name "*.dylib" -delete 2>/dev/null || true
find "$VENDOR" -name "*.pyc" -delete 2>/dev/null || true
find "$VENDOR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR" -path "*/tests" -type d -exec rm -rf {} + 2>/dev/null || true
find "$APP_ROOT" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ---------- 5. 二进制扫描 ----------
echo "==> 扫描架构相关文件"
BIN_HITS="$(find "$APP_ROOT" \( -name "*.so" -o -name "*.pyd" -o -name "*.dylib" \) -print 2>/dev/null | head -20)"
ELF_HITS="$(find "$APP_ROOT" -type f -size +0 -exec file {} \; 2>/dev/null | grep -E "ELF|Mach-O" | head -20 || true)"
if [ -n "$BIN_HITS" ] || [ -n "$ELF_HITS" ]; then
  echo "发现架构相关文件，platform=all 不成立："
  echo "$BIN_HITS"
  echo "$ELF_HITS"
  exit 1
fi
echo "    零二进制，platform=all 成立"

# ---------- 6. 依赖自检（禁止写字节码） ----------
echo "==> 依赖导入自检"
PYTHONPATH="$VENDOR" PYTHONDONTWRITEBYTECODE=1 "$(command -v python3)" - <<'PY'
import flask, waitress, markupsafe, jinja2, werkzeug
print("    flask/jinja2/werkzeug/markupsafe/waitress 均可导入")
print("    markupsafe backend:", "native" if not hasattr(markupsafe, "_speedups") else "speedups")
PY
find "$APP_ROOT" -name "*.pyc" -delete 2>/dev/null || true
find "$APP_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
PYC_LEFT="$(find "$APP_ROOT" -name "*.pyc" 2>/dev/null | wc -l)"
if [ "$PYC_LEFT" -gt 0 ]; then
  echo "仍有 $PYC_LEFT 个 .pyc，清理失败"; exit 1
fi

# ---------- 7. 生命周期脚本语法与顺序检查 ----------
echo "==> 生命周期脚本检查"
for f in "$PKG_DIR/cmd/"*; do
  bash -n "$f" || { echo "脚本语法错误：$f"; exit 1; }
done
# install_init 在解压前运行，禁止触碰数据目录（否则会以错误属主提前建目录）
if grep -qE 'mkdir[^|]*(TRIM_PKGVAR|TRIM_PKGETC)' "$PKG_DIR/cmd/install_init"; then
  echo "install_init 不得创建数据目录"; exit 1
fi
if grep -qE '\-w[[:space:]]+"?\$\{?(TRIM_PKGVAR|VAR_DIR)' "$PKG_DIR/cmd/install_init"; then
  echo "install_init 不得判断数据目录可写性"; exit 1
fi

# ---------- 8. 写入版本 ----------
sed -i.bak "s/^version *=.*/version = $VERSION/" "$PKG_DIR/manifest" && rm -f "$PKG_DIR/manifest.bak"

# ---------- 9. fnpack 构建 ----------
if [ -z "${FNPACK:-}" ]; then
  FNPACK="$ROOT/.cache/fnpack"
  if [ ! -x "$FNPACK" ]; then
    mkdir -p "$(dirname "$FNPACK")"
    echo "==> 下载 fnpack 1.2.3"
    curl -fsSL -o "$FNPACK" https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64
    chmod +x "$FNPACK"
  fi
fi

echo "==> 执行 fnpack build"
cd "$ROOT/build"
"$FNPACK" build --directory "$PKG_DIR" || { echo "fnpack 构建失败，终止"; exit 1; }

FPK="$ROOT/build/ship-pms.fpk"
[ -f "$FPK" ] || FPK="$(ls -t "$ROOT"/build/*.fpk | head -1)"
VERSIONED="$ROOT/build/ship-pms_${VERSION}.fpk"
cp -f "$FPK" "$VERSIONED"

# ---------- 10. 结构与内容校验 ----------
echo "==> 校验包结构"
TMP="$(mktemp -d)"
tar xzf "$FPK" -C "$TMP" 2>/dev/null || { echo "解包失败"; exit 1; }

REQUIRED=("app.tgz" "cmd/main" "cmd/install_init" "cmd/install_callback" "config/privilege" "config/resource" "wizard" "manifest" "ICON.PNG" "ICON_256.PNG")
for item in "${REQUIRED[@]}"; do
  [ -e "$TMP/$item" ] || { echo "缺少必要项: $item"; exit 1; }
done
[ -x "$TMP/cmd/install_callback" ] || { echo "cmd/install_callback 缺少执行权限"; exit 1; }

INNER_MD5="$(md5sum "$TMP/app.tgz" | awk '{print $1}')"
DECLARED="$(grep -E '^ *checksum *=' "$TMP/manifest" | cut -d= -f2 | tr -d ' ')"
[ -n "$DECLARED" ] || { echo "manifest 缺少 checksum"; exit 1; }
[ "$INNER_MD5" = "$DECLARED" ] || { echo "校验和不匹配: 实际 $INNER_MD5 / 声明 $DECLARED"; exit 1; }

echo "==> 校验 app.tgz 内容"
tar tzf "$TMP/app.tgz" > "$TMP/list.txt" 2>/dev/null
for inner in "wsgi.py" "app.py" "config.py" "vendor/flask/__init__.py" "ui/config" "ui/images/icon_64.png" "static/css/base.css" "templates/base.html"; do
  grep -qx "$inner" "$TMP/list.txt" || { echo "app.tgz 缺少 $inner"; exit 1; }
done
if grep -qE "\.(so|pyd|dylib|pyc)$" "$TMP/list.txt"; then
  echo "app.tgz 内含架构文件或字节码"; exit 1
fi

rm -rf "$TMP"

SIZE="$(du -h "$VERSIONED" | cut -f1)"
echo ""
echo "构建完成: $VERSIONED ($SIZE)"
echo "校验: 结构齐全 · checksum 一致 · 零二进制 · 零字节码 · 安装时序正确"

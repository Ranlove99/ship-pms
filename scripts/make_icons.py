"""生成应用图标：ICON.PNG(64) / ICON_256.PNG(256) 与桌面入口图标。

深海军蓝底 + 白色船体 + 安全橙桅杆与水线。几何形状，无文字，小尺寸下仍可辨认。
"""
import os

from PIL import Image, ImageDraw

BG = (14, 34, 48, 255)
FG = (250, 248, 244, 255)
ACC = (178, 69, 28, 255)

S = 1024
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "packaging")
UI_DIR = os.path.join(ROOT, "packaging", "app", "ui", "images")


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=196, fill=BG)

    # 桅杆
    d.rectangle((486, 206, 534, 668), fill=ACC)
    # 主帆（三角，底边与甲板贴合）
    d.polygon([(534, 246), (534, 640), (790, 640)], fill=FG)
    # 船体
    d.polygon([(188, 648), (836, 648), (740, 838), (284, 838)], fill=FG)
    # 水线
    d.rectangle((188, 886, 836, 916), fill=ACC)

    return img


def save(img: Image.Image, path: str, size: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(path, "PNG", optimize=True)


def main() -> None:
    icon = draw_icon()
    save(icon, os.path.join(OUT_DIR, "ICON.PNG"), 64)
    save(icon, os.path.join(OUT_DIR, "ICON_256.PNG"), 256)
    save(icon, os.path.join(UI_DIR, "icon_64.png"), 64)
    save(icon, os.path.join(UI_DIR, "icon_256.png"), 256)
    print("icons written to", OUT_DIR, "and", UI_DIR)


if __name__ == "__main__":
    main()

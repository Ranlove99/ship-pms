"""允许 `python -m db.seed k=v ...` 直接初始化。"""
import sys

from db.seed import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

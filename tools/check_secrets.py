#!/usr/bin/env python3
"""仓库自查：不该出现在公开仓库里的东西，一样都不许有。

只查**通用形态**（密钥、绝对用户路径、账号 ID 形态），不查任何具体名字——
具体名字写进这里就等于把名字公开了。

    python tools/check_secrets.py [目录]

退出码 0 = 干净；1 = 有问题（逐条打印）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: 目录名/文件名要跳过
SKIP_DIRS = {".git", ".github", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_FILES = {Path(__file__).name}

#: (说明, 正则)。顺序即报告顺序。
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JWT 形态的 token", re.compile(r"eyJ[A-Za-z0-9_\-]{16,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}")),
    ("OpenAI 风格 key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("绝对用户路径", re.compile(r"[A-Za-z]:[/\\]Users[/\\][^\\/\s\"']+")),
    ("24 位十六进制 ID", re.compile(r"\b[0-9a-f]{24}\b")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
)


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.name in SKIP_FILES:
            continue
        yield rel, path


def scan(root: Path) -> list[str]:
    problems: list[str] = []
    for rel, path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{rel.as_posix()}:{line} {label}：{match.group(0)[:32]!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    problems = scan(root)
    if problems:
        print("仓库自查没通过：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"仓库自查通过：{root} 里没有密钥、绝对用户路径或账号 ID 形态的字符串。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

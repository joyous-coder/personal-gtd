"""打包：跨机器安装用的源码包（zip）。

为什么需要：vault 里的 skill 目录会跟着笔记同步走，同步可能只带上部分文件，
也可能把 `__pycache__` 里的字节码一起带走——字节码绑定 Python 版本，
另一台机器上"装好了却 import 不了"。这个包只含源码，是安装的正规途径。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

#: 这些目录整个不要进包
EXCLUDED_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".obsidian",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
    }
)

#: 这些后缀的文件不要进包
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})


@dataclass(frozen=True)
class PackResult:
    """打包结果：包内文件与被排除的文件（都是相对 skill 根的路径）。"""

    archive: str
    files: tuple[str, ...]
    skipped: tuple[str, ...]


def collect_files(root: Path) -> tuple[list[str], list[str]]:
    """扫描 skill 根目录，返回 `(要打包的相对路径, 被排除的相对路径)`。"""
    root = Path(root)
    kept: list[str] = []
    skipped: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIR_NAMES for part in rel.parts[:-1]):
            skipped.append(rel.as_posix())
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            skipped.append(rel.as_posix())
            continue
        kept.append(rel.as_posix())
    return kept, skipped


def build_pack(root: Path, out: Path, name: str = "personal-gtd") -> PackResult:
    """把 skill 根目录打成 zip；包内顶层目录名为 `name`。"""
    root = Path(root)
    out = Path(out)
    kept, skipped = collect_files(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in kept:
            archive.write(root / rel, f"{name}/{rel}")
    return PackResult(archive=str(out), files=tuple(kept), skipped=tuple(skipped))

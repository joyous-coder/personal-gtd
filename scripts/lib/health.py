"""安装自检：源码是否齐全、有没有字节码污染、依赖与写入后端是否就绪。

为什么单独一个模块：`scripts/gtd.py` 要在导入其它 lib 模块**之前**用它做预检——
源码缺失时只剩 `.pyc`，而字节码与 Python 版本绑定，等 import 失败再报错会变成
难懂的 `ModuleNotFoundError`。所以这里只用标准库，也不 import 其它 lib 模块
（环境变量名与 `lib.notes` 一致，见 `tests/test_health.py` 里的防漂移测试）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

#: `scripts/lib/` 下必须存在的模块；少一个整个 skill 都跑不起来
#: `gtd.py` 在导入期就会 import 其中的每一个；缺任何一个都要在预检阶段点名，
#: 否则会抛 `ModuleNotFoundError`（正是预检要消灭的报错）。
#: `scripts/gtd` / `scripts/gtd.cmd` 里有一份同样的清单，测试保证两边同步。
REQUIRED_MODULES = (
    "config",
    "dida",
    "health",
    "models",
    "notes",
    "pack",
    "report",
    "review_note",
    "scoring",
    "settle",
)

# 与 `lib.notes` 保持一致；这里不 import 它，是为了让预检不牵动任何重模块
ENV_FNS_URL = "PERSONAL_GTD_FNS_URL"
ENV_FNS_TOKEN = "PERSONAL_GTD_FNS_TOKEN"
ENV_VAULT_DIR = "PERSONAL_GTD_VAULT_DIR"

#: 本文件所在目录就是 `scripts/lib`
DEFAULT_LIB_DIR = Path(__file__).resolve().parent

#: 写入后端的三种状态
WRITER_FNS = "fns"
WRITER_FOLDER = "folder"
WRITER_NONE = "none"


@dataclass(frozen=True)
class ModuleState:
    """一个模块的源码/字节码状态。"""

    name: str
    has_source: bool
    has_bytecode: bool


@dataclass(frozen=True)
class HealthReport:
    """一次自检的结论。`problems` 是致命的，`warnings` 只是提醒。"""

    lib_dir: str
    python_version: str
    modules: tuple[ModuleState, ...]
    missing_sources: tuple[str, ...]
    stray_bytecode: tuple[str, ...]
    dida_installed: bool
    dida_token_found: bool
    writer: str
    problems: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """源码齐全才算安装可用。"""
        return not self.problems


def scan_modules(lib_dir: Path) -> list[ModuleState]:
    """看每个必需模块有没有 `.py` 源码、`__pycache__` 里有没有对应字节码。"""
    lib_dir = Path(lib_dir)
    pycache = lib_dir / "__pycache__"
    states: list[ModuleState] = []
    for name in REQUIRED_MODULES:
        has_bytecode = (
            any(pycache.glob(f"{name}.*.pyc")) if pycache.is_dir() else False
        )
        states.append(
            ModuleState(
                name=name,
                has_source=(lib_dir / f"{name}.py").is_file(),
                has_bytecode=has_bytecode,
            )
        )
    return states


def find_stray_bytecode(lib_dir: Path) -> list[str]:
    """列出 `lib/` 下所有 `.pyc/.pyo`，路径相对 `lib/`（用 `/` 分隔）。"""
    lib_dir = Path(lib_dir)
    if not lib_dir.is_dir():
        return []
    return [
        path.relative_to(lib_dir).as_posix()
        for path in sorted(lib_dir.rglob("*.py[co]"))
        if path.is_file()
    ]


def check_install(lib_dir: Path) -> tuple[list[str], list[str]]:
    """返回 `(缺源码的模块名, 残留字节码相对路径)`。"""
    states = scan_modules(lib_dir)
    missing = [state.name for state in states if not state.has_source]
    return missing, find_stray_bytecode(lib_dir)


def _dida_token_found(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(raw.get("access_token")) if isinstance(raw, dict) else False


def build_report(
    lib_dir: Path | None = None,
    *,
    env=None,
    which=None,
    dida_token_path: Path | None = None,
) -> HealthReport:
    """跑一遍自检。`env`/`which`/`dida_token_path` 可注入，便于测试。"""
    lib_dir = Path(lib_dir) if lib_dir is not None else DEFAULT_LIB_DIR
    env = os.environ if env is None else env
    which = shutil.which if which is None else which

    states = scan_modules(lib_dir)
    missing = tuple(state.name for state in states if not state.has_source)
    stray = tuple(find_stray_bytecode(lib_dir))

    problems: list[str] = []
    for name in missing:
        problems.append(
            f"模块 {name} 没有 .py 源码（只同步到 .pyc 也算缺）。"
            "字节码与 Python 版本绑定，换机器/换版本就失效；"
            "请用 `gtd pack` 打出源码包，解压覆盖后重装。"
        )

    warnings: list[str] = []
    if stray:
        orphans = [
            path
            for path in stray
            if path.rsplit("/", 1)[-1].split(".")[0] in missing
        ]
        detail = f"，其中 {len(orphans)} 个没有对应源码" if orphans else ""
        warnings.append(
            f"lib/ 下有 {len(stray)} 个 .pyc 产物{detail}：本机是正常的，"
            "但它们不该跟着 vault 同步到别的机器（字节码绑定 Python 版本）。"
            "把 __pycache__ 和 *.pyc 排除出同步范围。"
        )

    dida_installed = bool(which("dida"))
    token_found = _dida_token_found(dida_token_path)
    if not dida_installed:
        warnings.append("PATH 里找不到 dida：npm i -g @suibiji/dida-cli（Node >= 20）。")
    elif not token_found:
        warnings.append(f"没读到滴答 token：{dida_token_path}")

    url = (env.get(ENV_FNS_URL) or "").strip()
    token = (env.get(ENV_FNS_TOKEN) or "").strip()
    folder = (env.get(ENV_VAULT_DIR) or "").strip()
    if url and token:
        writer = WRITER_FNS
    elif folder:
        writer = WRITER_FOLDER
    else:
        writer = WRITER_NONE
        warnings.append(
            f"没配置写入后端：settle / balance / backfill / audit / report / monthly 会退出 1。"
            f"设置 {ENV_FNS_URL} + {ENV_FNS_TOKEN}，或 {ENV_VAULT_DIR}。"
        )

    return HealthReport(
        lib_dir=str(lib_dir),
        python_version=sys.version.split()[0],
        modules=tuple(states),
        missing_sources=missing,
        stray_bytecode=stray,
        dida_installed=dida_installed,
        dida_token_found=token_found,
        writer=writer,
        problems=tuple(problems),
        warnings=tuple(warnings),
    )


def render_report(report: HealthReport) -> str:
    """把自检结果渲染成给人看的中文报告。"""
    total = len(report.modules)
    have = sum(1 for state in report.modules if state.has_source)
    lines = [
        "personal-gtd 安装自检",
        f"Python：{report.python_version}",
        f"源码模块：{have}/{total} 齐全",
        f"写入后端：{report.writer}",
        f"滴答清单：{'已安装' if report.dida_installed else '未安装'}"
        f" / token {'已找到' if report.dida_token_found else '未找到'}",
        f"检查目录：{report.lib_dir}",
    ]
    if report.problems:
        lines.append("[问题]")
        lines.extend(f"  - {item}" for item in report.problems)
    if report.warnings:
        lines.append("[提示]")
        lines.extend(f"  - {item}" for item in report.warnings)
    lines.append("结论：" + ("安装正常" if report.ok else "安装不完整，先修上面的问题"))
    return "\n".join(lines)

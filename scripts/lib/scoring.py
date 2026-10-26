"""personal-gtd 纯计分函数：不碰 IO、不读配置，只做确定的数值换算。

积分标记约定：任务标题末尾的 `$N` 是显式标价；习惯名里任意位置的 `$N` 是单次全额，
`%N` 是目标次数；名字前导 `@` 只是排序前缀，计分时去掉。
"""

from __future__ import annotations

import math
import re
from typing import Sequence

from .models import Task

_TASK_POINTS_RE = re.compile(r"\s*\$(\d+(?:\.\d+)?)\s*$")
_HABIT_POINTS_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_POINTS_TOKEN_RE = re.compile(r"\$\s*\d+(?:\.\d+)?")
_GOAL_TOKEN_RE = re.compile(r"%\s*\d+(?:\.\d+)?")
_LEADING_AT_RE = re.compile(r"^\s*@\s*")

_PRIORITY_BASE = {5: 3.0, 3: 2.0, 1: 1.0}
_DEFAULT_PRIORITY_BASE = 0.5

#: 规模系数（设计稿 §5.2）：只用于「新建/排程时预填 `$N`」，结算不乘
SIZE_FACTORS: dict[str, float] = {"S": 1.0, "M": 1.5, "L": 2.0}
DEFAULT_SIZE = "S"


def parse_task_points(title: str) -> float | None:
    """只认标题末尾的 `$N`；正文中间出现的价格标记不算。"""
    match = _TASK_POINTS_RE.search(title or "")
    return float(match.group(1)) if match else None


def parse_habit_points(name: str) -> float | None:
    """习惯名的 `$N` 可以出现在任意位置，取第一个。"""
    match = _HABIT_POINTS_RE.search(name or "")
    return float(match.group(1)) if match else None


def priority_base(priority: int) -> float:
    """滴答优先级到基础分：5→3、3→2、1→1，其余（含 0、2、None）→0.5。"""
    return _PRIORITY_BASE.get(priority, _DEFAULT_PRIORITY_BASE)


def size_factor(size: str) -> float:
    """规模系数：S（≤1 番茄）1、M（2–3）1.5、L（≥4）2；未知取值报错。"""
    key = str(size or DEFAULT_SIZE).strip().upper()
    try:
        return SIZE_FACTORS[key]
    except KeyError as exc:
        raise ValueError(f"未知规模 {size!r}，只支持 {', '.join(SIZE_FACTORS)}") from exc


def task_prefill_points(task: Task, size: str = DEFAULT_SIZE) -> float:
    """新建/排程时 AI 预填的分：显式 `$N` 优先，否则「优先级底分 × 规模系数」。

    只给 `score` 用；结算走 `task_effective_points`，**不乘规模**
    （设计稿 §5.2：没写 `$` 时按优先级底分，避免隐式计分）。
    """
    explicit = parse_task_points(task.title)
    if explicit is not None:
        return explicit
    return priority_base(task.priority) * size_factor(size)


def round_half(value: float) -> float:
    """四舍五入到 0.5 的网格，0.25 进位到 0.5（不用银行家舍入）。"""
    return math.floor(value * 2 + 0.5) / 2


def habit_points(name: str, goal: float, value: float) -> float:
    """习惯得分：按 value/goal 折算，最多拿全额；没标 `$` 一律 0。"""
    points = parse_habit_points(name)
    if points is None:
        return 0.0
    if goal <= 0:
        return points if value > 0 else 0.0
    return round_half(points * min(1.0, value / goal))


def normalize_name(name: str) -> str:
    """去掉 `$N`、`%N`、前导 `@`，压缩空白——用于跟滴答侧的名字对齐。"""
    text = _POINTS_TOKEN_RE.sub("", name or "")
    text = _GOAL_TOKEN_RE.sub("", text)
    text = _LEADING_AT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def is_breakthrough(tags: Sequence[str], tag: str = "突破") -> bool:
    return tag in (tags or ())


def is_consumption(tags: Sequence[str], tag: str = "积分消费") -> bool:
    return tag in (tags or ())


def task_effective_points(task: Task) -> float | None:
    """任务的有效积分。

    父任务（有子任务）整条忽略，即使写了 `$N`；子任务必须显式标价，
    否则记 0（避免每片都白拿底分）；无 `$N` 的重复任务不计分。
    """
    if task.child_ids:
        return None
    explicit = parse_task_points(task.title)
    if explicit is not None:
        return explicit
    if task.parent_id:
        return 0.0
    if task.repeat_flag:
        return None
    return priority_base(task.priority)


def task_final_points(
    task: Task,
    *,
    late_subjective: bool,
    breakthrough: bool,
    points: float | None = None,
) -> tuple[float, bool]:
    """返回 (最终积分, 是否逾期)。主观逾期且非突破任务时积分减半。

    `points` 给定时用它当有效分（`score` 的规模系数预填），否则按
    `task_effective_points`（结算口径，不乘规模）。
    """
    if points is None:
        points = task_effective_points(task) or 0.0
    late = bool(
        task.due_date and task.completed_time and task.completed_time > task.due_date
    )
    if late and late_subjective and not breakthrough:
        points = points * 0.5
    return points, late

"""personal-gtd 领域模型：项目、任务、习惯、专注记录。

全部是不可变 dataclass，只为在计分与归档之间传递数据，不承载任何 IO。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Project:
    id: str
    name: str


@dataclass(frozen=True)
class Task:
    id: str
    project_id: str
    project_name: str
    title: str
    priority: int = 0
    due_date: datetime | None = None
    start_date: datetime | None = None
    completed_time: datetime | None = None
    repeat_flag: str | None = None
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    estimated_pomo: int | None = None
    content: str | None = None


@dataclass(frozen=True)
class Habit:
    id: str
    name: str
    goal: float = 1.0


@dataclass(frozen=True)
class FocusTask:
    task_id: str
    start: datetime
    end: datetime

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(frozen=True)
class FocusRecord:
    id: str
    type: int
    start: datetime
    end: datetime
    tasks: tuple[FocusTask, ...] = ()

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    def minutes_for(self, task_id: str) -> float:
        return sum(t.minutes for t in self.tasks if t.task_id == task_id)


@dataclass(frozen=True)
class DayInputs:
    """一天的结算输入：任务、习惯打卡、专注记录，以及跨天滚动过来的账本快照。"""

    day: date
    tasks: tuple[Task, ...] = ()
    habits: tuple[Habit, ...] = ()
    habit_values: dict[str, float] = field(default_factory=dict)
    focus: tuple[FocusRecord, ...] = ()
    late_subjective_ids: frozenset[str] = frozenset()
    previous_spendable: float = 0.0
    weekly_earned_before: float = 0.0
    weekly_spent_before: float = 0.0
    weekly_penalty_pending: bool = False


@dataclass(frozen=True)
class ItemScore:
    """单条计分明细，供日回顾正文渲染。

    kind：`task` 任务、`habit` 习惯、`consumption` 积分消费。
    points 是计入当日收入的分数（消费恒为 0），planned 是计入分母的计划分。
    """

    kind: str
    id: str
    name: str
    points: float = 0.0
    planned: float = 0.0
    late: bool = False
    discounted: bool = False


@dataclass(frozen=True)
class DayScore:
    """一天结算后的完整账本快照，字段与日回顾 frontmatter 一一对应。"""

    day: date
    kind: str = "workday"
    earned_task: float = 0.0
    earned_habit: float = 0.0
    earned_total: float = 0.0
    planned_total: float = 0.0
    denominator: float = 0.0
    rate: float = 0.0
    late_discount: float = 0.0
    late_pending: bool = False
    reserve: float = 0.0
    spendable: float = 0.0
    spent_daily: float = 0.0
    spent_weekly: float = 0.0
    unmet_minutes: float = 0.0
    unmet_points: float = 0.0
    daily_balance: float = 0.0
    weekly_earned: float = 0.0
    weekly_spent: float = 0.0
    weekly_balance: float = 0.0
    weekly_penalty_pending: bool = False
    penalty_applied: bool = False
    items: tuple[ItemScore, ...] = ()

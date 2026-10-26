"""personal-gtd 日结算：把一天的任务、习惯、专注记录折成 DayScore。

纯函数，只读 DayInputs 与 Config，不碰 IO。顺序固定：

kind → planned → 完成计分 → 习惯计分 + 同名去重 → planned_total → denominator
→ earned_total/rate → spendable → penalty → 消费 → 周账 → daily_balance
→ late_pending → late_discount/items。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import Config
from .models import DayInputs, DayScore, ItemScore, Task
from .scoring import (
    habit_points,
    is_breakthrough,
    is_consumption,
    normalize_name,
    parse_task_points,
    task_effective_points,
    task_final_points,
)

WORKDAY = "workday"
WEEKEND = "weekend"


@dataclass
class _Entry:
    """结算过程中的可变明细条目，最后折成 ItemScore。"""

    task: Task
    points: float
    late: bool
    counted: bool
    discounted: bool
    consumption: bool
    breakthrough: bool


def _planned_on(task: Task, day: date) -> bool:
    """任务当天是否排进计划：截止日或开始日落在当天。"""
    for stamp in (task.due_date, task.start_date):
        if stamp is not None and stamp.date() == day:
            return True
    return False


def _is_on(stamp, day: date) -> bool:
    return stamp is not None and stamp.date() == day


def _rate(value: float) -> float:
    """换算率兜底：配置被写成 0 或负数时不至于除零。"""
    return value if value > 0 else 1.0


def settle_day(inputs: DayInputs, config: Config) -> DayScore:
    cfg = config
    day = inputs.day
    kind = WEEKEND if day.weekday() >= 5 else WORKDAY
    consumption_tag = cfg.tags.get("consumption", "积分消费")
    breakthrough_tag = cfg.tags.get("breakthrough", "突破")

    # 2. 计划：当天到期/开始，排除积分消费，排除“重复且无显式 $”的提醒类任务
    planned = [
        t
        for t in inputs.tasks
        if _planned_on(t, day)
        and not is_consumption(t.tags, consumption_tag)
        and not (t.repeat_flag and parse_task_points(t.title) is None)
    ]

    # 3. 完成计分
    entries: list[_Entry] = []
    for t in inputs.tasks:
        if not _is_on(t.completed_time, day):
            continue
        consumption = is_consumption(t.tags, consumption_tag)
        breakthrough = is_breakthrough(t.tags, breakthrough_tag)
        late_subjective = t.id in inputs.late_subjective_ids
        final, late = task_final_points(
            t, late_subjective=late_subjective, breakthrough=breakthrough
        )
        effective = task_effective_points(t) or 0.0
        counted = effective > 0 and not consumption
        discounted = bool(counted and late and late_subjective and not breakthrough)
        entries.append(
            _Entry(
                task=t,
                points=0.0 if consumption else final,
                late=late,
                counted=counted,
                discounted=discounted,
                consumption=consumption,
                breakthrough=breakthrough,
            )
        )

    # 4. 习惯分，随后与任务同名去重：任务显式 $ 优先，否则习惯优先、任务让位
    habit_rows: list[list] = []  # [id, name, points]
    for habit in inputs.habits:
        value = inputs.habit_values.get(habit.id, 0.0)
        habit_rows.append(
            [habit.id, habit.name, habit_points(habit.name, habit.goal, value)]
        )

    dropped_ids: set[str] = set()
    for row in habit_rows:
        habit_id, habit_name, habit_score = row
        if habit_score <= 0:
            continue
        target = next(
            (e for e in entries if normalize_name(e.task.title) == normalize_name(habit_name)),
            None,
        )
        if target is None:
            continue
        if parse_task_points(target.task.title) is not None:
            row[2] = 0.0
        else:
            target.points = 0.0
            target.counted = False
            target.discounted = False
            dropped_ids.add(target.task.id)

    if dropped_ids:
        planned = [t for t in planned if t.id not in dropped_ids]
    planned_ids = {t.id for t in planned}

    # 5. 计划总价与 6. 分母
    planned_total = sum(task_effective_points(t) or 0.0 for t in planned)
    denominator = min(cfg.daily_cap, max(30.0, planned_total))

    # 7. 收入与完成率
    earned_task = sum(e.points for e in entries)
    earned_habit = sum(row[2] for row in habit_rows)
    earned_total = earned_task + earned_habit
    rate = round(min(1.0, earned_total / denominator), 3) if denominator else 0.0

    # 8. 可花分
    spendable = max(0.0, min(earned_total, cfg.daily_cap) - cfg.reserve)

    # 9. 触发惩罚
    penalty_applied = any(
        habit.name == cfg.penalty_habit and inputs.habit_values.get(habit.id, 0.0) >= 1
        for habit in inputs.habits
    )
    if penalty_applied:
        spendable = spendable / 3.0

    # 10. 积分消费
    weekly_available = max(
        0.0,
        min(cfg.weekly_cap, inputs.weekly_earned_before + earned_total)
        - inputs.weekly_spent_before,
    )
    day_pool = inputs.previous_spendable
    week_pool = weekly_available
    spent_daily = 0.0
    spent_weekly = 0.0
    unmet_minutes = 0.0
    unmet_points = 0.0

    for entry in entries:
        if not entry.consumption:
            continue
        task_id = entry.task.id
        minutes = sum(r.minutes_for(task_id) for r in inputs.focus)
        if minutes > 0:
            daily = min(minutes / _rate(cfg.day_rate), day_pool)
            spent_daily += daily
            day_pool -= daily
            leftover_minutes = max(0.0, minutes - daily * _rate(cfg.day_rate))
            if kind == WEEKEND:
                weekly = min(leftover_minutes / _rate(cfg.week_rate), week_pool)
                spent_weekly += weekly
                week_pool -= weekly
                unmet_minutes += max(
                    0.0, leftover_minutes - weekly * _rate(cfg.week_rate)
                )
            else:
                unmet_minutes += leftover_minutes
        else:
            cost = parse_task_points(entry.task.title) or 0.0
            daily = min(cost, day_pool)
            spent_daily += daily
            day_pool -= daily
            leftover_points = max(0.0, cost - daily)
            if kind == WEEKEND:
                weekly = min(leftover_points, week_pool)
                spent_weekly += weekly
                week_pool -= weekly
                unmet_points += max(0.0, leftover_points - weekly)
            else:
                unmet_points += leftover_points

    # 11. 周账
    weekly_earned = inputs.weekly_earned_before + earned_total
    weekly_spent = inputs.weekly_spent_before + spent_weekly
    weekly_balance = max(0.0, min(cfg.weekly_cap, weekly_earned) - weekly_spent)

    weekly_penalty = inputs.weekly_penalty_pending or penalty_applied
    if kind == WEEKEND:
        if weekly_penalty:
            weekly_balance = weekly_balance / 3.0
        weekly_penalty_pending = False
    else:
        weekly_penalty_pending = weekly_penalty

    # 12. 日结余
    daily_balance = spendable

    # 13. 待确认的逾期
    late_pending = any(
        e.late
        and e.counted
        and e.task.id not in inputs.late_subjective_ids
        and not e.breakthrough
        for e in entries
    )

    # 14. 逾期折扣与明细
    late_discount = sum(
        round((task_effective_points(e.task) or 0.0) * 0.5, 2)
        for e in entries
        if e.discounted
    )

    items: list[ItemScore] = [
        ItemScore(
            kind="consumption" if e.consumption else "task",
            id=e.task.id,
            name=e.task.title,
            points=e.points,
            planned=(
                (task_effective_points(e.task) or 0.0)
                if e.task.id in planned_ids
                else 0.0
            ),
            late=e.late,
            discounted=e.discounted,
        )
        for e in entries
    ]
    items.extend(
        ItemScore(kind="habit", id=habit_id, name=habit_name, points=habit_score)
        for habit_id, habit_name, habit_score in habit_rows
    )
    items.sort(key=lambda item: (item.id, item.kind))

    return DayScore(
        day=day,
        kind=kind,
        earned_task=earned_task,
        earned_habit=earned_habit,
        earned_total=earned_total,
        planned_total=planned_total,
        denominator=denominator,
        rate=rate,
        late_discount=late_discount,
        late_pending=late_pending,
        reserve=cfg.reserve,
        spendable=spendable,
        spent_daily=spent_daily,
        spent_weekly=spent_weekly,
        unmet_minutes=unmet_minutes,
        unmet_points=unmet_points,
        daily_balance=daily_balance,
        weekly_earned=weekly_earned,
        weekly_spent=weekly_spent,
        weekly_balance=weekly_balance,
        weekly_penalty_pending=weekly_penalty_pending,
        penalty_applied=penalty_applied,
        items=tuple(items),
    )

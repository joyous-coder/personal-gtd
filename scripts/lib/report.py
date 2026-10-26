"""周报与月报：汇总日回顾 frontmatter，算完成率与月金额，渲染回顾 Markdown。

数据只来自日回顾的 frontmatter（`721-日维度`），不另存账本（设计稿 §6）：

- 周汇总：区间内 `earned_total` / `planned_total` 求和，
  `rate = min(1, 收入 / min(60, max(30, 计划合计)))`。
- 月完成率 = avg(工作日完成率, 双休完成率)：
  - 工作日完成率：各工作日 `rate` 的平均；
  - 双休完成率：按 ISO 周把周六/周日配成一组，`收入 = 组内和`、
    `分母 = min(60, max(30, 计划合计))`、`完成率 = min(1, 收入 / 分母)`，再平均。
    单独的一天（只结算了周六或周日）自成一组，公式不变。
- 月金额：总完成率 < 门槛 → 0；否则 `工资 × 预算比例 × 总完成率`；
  当月任一天 `penalty_applied` 为真 → 金额再扣 2/3（当月只扣一次）。
- 完成率封顶 100%，金额因此封顶「工资 × 预算比例」。

输入是 frontmatter 字典（值可能是字符串）：数值字段先 `float()`，
`penalty_applied` 按 `true`/`false` 解析；`kind` 缺失时按日期推工作日/双休。

本模块只做纯计算与渲染，不碰任何 IO 后端；读笔记、取配置留在 `gtd.py`。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
WEEKLY_TEMPLATE_PATH = ASSETS_DIR / "review-weekly.md"
MONTHLY_TEMPLATE_PATH = ASSETS_DIR / "review-monthly.md"

WORKDAY = "workday"
WEEKEND = "weekend"

#: 日/周分母的上下限（设计稿 §5.7：min(60, max(30, 计划合计))）
DENOM_CAP = 60.0
DENOM_FLOOR = 30.0

#: 判门槛时容忍浮点误差：0.5999999999999 不该被判成低于 0.6
_EPSILON = 1e-9

KIND_LABELS = {WORKDAY: "工作日", WEEKEND: "双休"}

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

_WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


# ---------- 取值 ----------


def _optional_float(value: object) -> float | None:
    """解析数值；解析不出来返回 None（要区分「缺失」与 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float:
    number = _optional_float(value)
    return 0.0 if number is None else number


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _day_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _day_kind(day: Mapping[str, object]) -> str:
    """frontmatter 的 `kind` 优先；缺失或不认识时按日期推（周六/周日算双休）。"""
    raw = str(day.get("kind") or "").strip().lower()
    if raw in (WORKDAY, WEEKEND):
        return raw
    parsed = _day_date(day.get("date"))
    if parsed is not None and parsed.weekday() >= 5:
        return WEEKEND
    return WORKDAY


def _day_rate(day: Mapping[str, object]) -> float:
    """`rate` 优先；缺了就按 `earned_total / denominator` 现算。"""
    parsed = _optional_float(day.get("rate"))
    if parsed is not None:
        return parsed
    denominator = _as_float(day.get("denominator"))
    if denominator > 0:
        return _as_float(day.get("earned_total")) / denominator
    return 0.0


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _denominator(planned: float) -> float:
    return min(DENOM_CAP, max(DENOM_FLOOR, planned))


def has_penalty(days: Sequence[Mapping[str, object]]) -> bool:
    """区间内是否有一天触发过惩罚（触发）——月金额只扣一次。"""
    return any(_as_bool(day.get("penalty_applied")) for day in days)


def consumption_totals(days: Sequence[Mapping[str, object]]) -> dict[str, float]:
    """区间消费合计：日账与周账分开放（两本账互不抵扣，设计稿 §5.4）。"""
    return {
        "spent_daily": sum(_as_float(day.get("spent_daily")) for day in days),
        "spent_weekly": sum(_as_float(day.get("spent_weekly")) for day in days),
    }


# ---------- 汇总 ----------


def weekly_summary(days: Sequence[Mapping[str, object]]) -> dict[str, float]:
    """区间汇总：收入/计划求和，完成率用同一个分母公式。"""
    earned_total = sum(_as_float(day.get("earned_total")) for day in days)
    planned_total = sum(_as_float(day.get("planned_total")) for day in days)
    denominator = _denominator(planned_total)
    rate = min(1.0, earned_total / denominator) if denominator > 0 else 0.0
    return {
        "earned_total": earned_total,
        "planned_total": planned_total,
        "rate": rate,
    }


def _weekend_bucket(day: Mapping[str, object], index: int) -> object:
    """同 ISO 周的双休日同组；日期不可解析时各自成组（避免误配）。"""
    parsed = _day_date(day.get("date"))
    if parsed is None:
        return ("unknown", index)
    iso = parsed.isocalendar()
    return (iso.year, iso.week)


def weekend_rate(days: Sequence[Mapping[str, object]]) -> float:
    """双休完成率：每个双休（周六+周日合计）算一次，再平均。"""
    buckets: dict[object, list[Mapping[str, object]]] = {}
    for index, day in enumerate(days):
        buckets.setdefault(_weekend_bucket(day, index), []).append(day)

    rates: list[float] = []
    for group in buckets.values():
        earned = sum(_as_float(day.get("earned_total")) for day in group)
        planned = sum(_as_float(day.get("planned_total")) for day in group)
        denominator = _denominator(planned)
        rates.append(min(1.0, earned / denominator) if denominator > 0 else 0.0)
    return _average(rates)


def monthly_summary(
    days: Sequence[Mapping[str, object]],
    *,
    salary: float,
    threshold: float,
    budget_rate: float,
) -> dict[str, float]:
    """月完成率与月金额（设计稿 §5.4「月账」）。

    返回 `weekday_rate` / `weekend_rate` / `overall_rate` / `money` /
    `salary` / `threshold`；金额已含门槛与惩罚，完成率封顶 100%。
    """
    workdays = [day for day in days if _day_kind(day) == WORKDAY]
    weekends = [day for day in days if _day_kind(day) == WEEKEND]

    weekday = _average([_day_rate(day) for day in workdays])
    weekend = weekend_rate(weekends)

    # 一侧没有数据就用另一侧，避免半个月的空窗把完成率拉成一半
    if workdays and weekends:
        overall = (weekday + weekend) / 2
    elif workdays:
        overall = weekday
    elif weekends:
        overall = weekend
    else:
        overall = 0.0
    overall = min(1.0, overall)

    limit = float(threshold)
    if overall + _EPSILON < limit:
        money = 0.0
    else:
        money = float(salary) * float(budget_rate) * overall
    if has_penalty(days):
        money /= 3

    return {
        "weekday_rate": weekday,
        "weekend_rate": weekend,
        "overall_rate": overall,
        "money": money,
        "salary": float(salary),
        "threshold": limit,
    }


# ---------- 渲染 ----------


def _num(value: object) -> str:
    """人读数值走 `:g` 口径（22 不写成 22.0）。"""
    number = _as_float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _ratio(value: object) -> str:
    return f"{_as_float(value):.3f}"


def _fill(template: str, values: Mapping[str, str]) -> str:
    """替换所有 `{{key}}`；模板里有未知占位符就报错，别静默留花括号。"""
    missing = sorted(
        {name for name in _PLACEHOLDER.findall(template) if name not in values}
    )
    if missing:
        raise ValueError(f"模板占位符没有取值: {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _sorted_days(days: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """按日期升序；日期不可解析的排最后（保持原顺序）。"""
    return sorted(days, key=lambda day: _day_date(day.get("date")) or date.max)


def _daily_rows(days: Sequence[Mapping[str, object]]) -> str:
    rows: list[str] = []
    for day in _sorted_days(days):
        parsed = _day_date(day.get("date"))
        weekday = _WEEKDAY_NAMES[parsed.weekday()] if parsed else ""
        rows.append(
            f"| {day.get('date') or ''} | {weekday} | "
            f"{KIND_LABELS[_day_kind(day)]} | "
            f"{_num(day.get('earned_total'))} | "
            f"{_num(day.get('planned_total'))} | "
            f"{_ratio(_day_rate(day))} |"
        )
    return "\n".join(rows) if rows else "| _无_ | | | | | |"


def render_weekly(
    days: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
) -> str:
    """渲染周/区间回顾 Markdown（frontmatter + 固定小节），只返回文本。"""
    summary = weekly_summary(days)
    spent = consumption_totals(days)
    values = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": str(len(days)),
        "earned_total": _num(summary["earned_total"]),
        "planned_total": _num(summary["planned_total"]),
        "rate": _ratio(summary["rate"]),
        "spent_daily": _num(spent["spent_daily"]),
        "spent_weekly": _num(spent["spent_weekly"]),
        "daily_rows": _daily_rows(days),
    }
    return _fill(WEEKLY_TEMPLATE_PATH.read_text(encoding="utf-8"), values)


def render_monthly(
    days: Sequence[Mapping[str, object]],
    *,
    month: str,
    salary: float,
    threshold: float,
    budget_rate: float,
) -> str:
    """渲染月回顾 Markdown（frontmatter + 固定小节），只返回文本。"""
    summary = monthly_summary(
        days,
        salary=salary,
        threshold=threshold,
        budget_rate=budget_rate,
    )
    # frontmatter 是机器可读层，布尔必须写小写 true/false；
    # 中文「是/否」只出现在正文（`_as_bool("是")` 会读成 False，别写进 frontmatter）
    penalty = has_penalty(days)
    values = {
        "month": month,
        "days": str(len(days)),
        "weekday_rate": _ratio(summary["weekday_rate"]),
        "weekend_rate": _ratio(summary["weekend_rate"]),
        "overall_rate": _ratio(summary["overall_rate"]),
        "salary": _num(summary["salary"]),
        "threshold": _ratio(summary["threshold"]),
        "budget_rate": _ratio(budget_rate),
        "money": f"{summary['money']:.2f}",
        "penalty_flag": "true" if penalty else "false",
        "penalty_label": "是" if penalty else "否",
    }
    return _fill(MONTHLY_TEMPLATE_PATH.read_text(encoding="utf-8"), values)

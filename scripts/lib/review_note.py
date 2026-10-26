"""日回顾渲染与 frontmatter 读写。

日回顾是当天唯一的日汇总落点：frontmatter 存机器可读的账本快照，正文存人读的
明细摘要（设计稿 §6）。本模块只管「DayScore → Markdown」以及 frontmatter 的
解析/替换，不碰任何 IO 后端（写入交给 `notes.py`）。

约定：
- 模板是 `assets/review-daily.md`，占位符写作 `{{key}}`，key 即 DayScore 字段名；
  另外支持 `{{weekday}}` / `{{rule_version}}` / `{{items}}` / `{{consumption}}`
  这类渲染期派生值。
- 数值格式：`rate` 固定 3 位小数（0.519）；其余分数走 `:g`（22 不写成 22.0）；
  布尔写小写 `true` / `false`；日期写 `YYYY-MM-DD`。
- `parse_frontmatter` 只解析首个 `---` 块，值一律返回字符串；解析失败不抛异常，
  当成「没有 frontmatter」。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Mapping

from .models import DayScore, ItemScore

RULE_VERSION = "v1"

#: frontmatter 键顺序，与设计稿 §6 一致；`date` 取自 `DayScore.day`。
FRONTMATTER_KEYS: tuple[str, ...] = (
    "date",
    "kind",
    "earned_task",
    "earned_habit",
    "earned_total",
    "planned_total",
    "denominator",
    "rate",
    "late_discount",
    "late_pending",
    "reserve",
    "spendable",
    "spent_daily",
    "spent_weekly",
    "unmet_minutes",
    "unmet_points",
    "daily_balance",
    "weekly_earned",
    "weekly_spent",
    "weekly_balance",
    "weekly_penalty_pending",
    "penalty_applied",
)

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

KIND_LABELS = {"task": "任务", "habit": "习惯", "consumption": "消费"}

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "assets" / "review-daily.md"

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

_FENCE = "---"

#: 收尾分隔符可以是 `---`，也可能是 YAML 的 `...`。
_DELIMITERS = (_FENCE, "...")


def _format_value(key: str, value: object) -> str:
    """按 frontmatter 约定格式化单值；字符串原样透出（保留人手写的精度）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        number = float(value)
        if key == "rate":
            return f"{number:.3f}"
        if number.is_integer():
            return str(int(number))
        return f"{number:g}"
    return str(value)


def frontmatter_values(score: DayScore) -> dict[str, str]:
    """把 DayScore 折成 frontmatter 的键值（全字符串），顺序同 FRONTMATTER_KEYS。"""
    values: dict[str, str] = {}
    for key in FRONTMATTER_KEYS:
        raw = score.day if key == "date" else getattr(score, key)
        values[key] = _format_value(key, raw)
    values["rule_version"] = RULE_VERSION
    return values


def _render_items(items: tuple[ItemScore, ...]) -> str:
    """`### 今日明细`：任务与习惯逐条列出，消费单独成节。"""
    rows: list[str] = []
    for item in items:
        if item.kind == "consumption":
            continue
        label = KIND_LABELS.get(item.kind, item.kind)
        row = f"- {label}「{item.name}」 {_format_value('points', item.points)} 分"
        if item.planned:
            row += f"（计划 {_format_value('planned', item.planned)}）"
        if item.late:
            row += "（滞后）"
        if item.discounted:
            row += "（已打折）"
        rows.append(row)
    return "\n".join(rows) if rows else "_无_"


def _render_consumption(items: tuple[ItemScore, ...]) -> str:
    """`### 消费`：逐条列出消费任务；金额由 spent_daily / spent_weekly 汇总。"""
    rows = [
        f"- {KIND_LABELS['consumption']}「{item.name}」"
        for item in items
        if item.kind == "consumption"
    ]
    return "\n".join(rows) if rows else "_无_"


def _fill(template: str, values: Mapping[str, str]) -> str:
    """替换所有 `{{key}}`；模板里出现未知占位符时报错，避免静默留下花括号。"""
    missing = sorted({name for name in _PLACEHOLDER.findall(template) if name not in values})
    if missing:
        raise ValueError(f"模板占位符没有取值: {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def render_daily(score: DayScore) -> str:
    """渲染一天的回顾 Markdown（frontmatter + 正文），结果以 `---\\n` 开头。"""
    values = frontmatter_values(score)
    values["weekday"] = WEEKDAYS[score.day.weekday()]
    values["items"] = _render_items(score.items)
    values["consumption"] = _render_consumption(score.items)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return _fill(template, values)


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """拆成 (frontmatter 内的行, 正文)；没有或未闭合的块当作没有 frontmatter。"""
    stripped = text.lstrip("\ufeff")
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return [], stripped
    for index in range(1, len(lines)):
        if lines[index].strip() in _DELIMITERS:
            return lines[1:index], "".join(lines[index + 1 :])
    return [], stripped


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> dict[str, object]:
    """只解析首个 `---` 块里的 `key: value`，值一律是字符串。"""
    lines, _ = _split_frontmatter(text)
    parsed: dict[str, object] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        if key:
            parsed[key] = _unquote(value.strip())
    return parsed


def replace_frontmatter(text: str, values: Mapping[str, object]) -> str:
    """替换/追加 frontmatter 键，正文原样保留（幂等改写同一篇日回顾）。"""
    pending = {key: _format_value(key, value) for key, value in values.items()}
    if not pending:
        return text
    lines, body = _split_frontmatter(text)

    kept: list[str] = []
    written: set[str] = set()
    for line in lines:
        raw = line.rstrip("\r\n")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            kept.append(raw)
            continue
        key = stripped.partition(":")[0].strip()
        if key in pending and key not in written:
            kept.append(f"{key}: {pending[key]}")
            written.add(key)
        else:
            kept.append(raw)
    kept.extend(f"{key}: {value}" for key, value in pending.items() if key not in written)

    block = f"{_FENCE}\n" + "".join(f"{line}\n" for line in kept) + f"{_FENCE}\n"
    return block + body

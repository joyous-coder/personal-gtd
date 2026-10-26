#!/usr/bin/env python3
"""personal-gtd 命令行入口：`score` / `settle` / `balance` / `backfill` / `audit` /
`report` / `monthly` / `init`。

数据流：滴答 Open API → `DayInputs` → `settle_day` → `DayScore` → `render_daily` → 笔记后端。

约定：
- 人类可读提示写中文；机器可读结果写 JSON（stdout）。
- 退出码：0 成功、1 配置/数据错误（含对账不一致）、2 参数错误（argparse 自己以 2 退出）。
- `settle --dry-run` 不读笔记、不写笔记，只打印 `DayScore` 的 JSON。
- 周账滚动：普通日接前一天日回顾的 frontmatter；周一强制把周赚/周花/待罚清零，
  但「今日可花」的起点仍取周日那条。读前一天笔记是三态的：缺笔记只提示「从 0 起算」，
  读失败（后端/HTTP 故障）直接退出 1，绝不把故障当成「没有」。
- `settle` 默认拒绝覆盖已存在的日回顾（保护人写的总结/确认/谋划/身份反馈），
  `--force` 才整篇重写；`backfill` 按日期升序逐天 `settle`，默认跳过已存在的日回顾。
- `balance` / `report` / `monthly` 只认带 `date` + `earned_total` 的账本 frontmatter；
  `1-日维度` 里老的自适应日总结（无 frontmatter）按「跳过」处理，不算 0% 的一天。
- `audit` 用滴答重算后与 frontmatter 对账；结算时确认过主观逾期的日子要带
  `--late-subjective IDS` 才能对上。
- `report` / `monthly` 只读日回顾 frontmatter，打印周/月回顾 Markdown，**不写文件**
  （v1 是否落盘由 Claude 决定）。
- 新命令都接受 `--vault-dir`，临时覆盖 `PERSONAL_GTD_VAULT_DIR`（测试与补账用）。
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

# 允许直接 `python scripts/gtd.py ...`：把 scripts/ 放进搜索路径，`lib.*` 才导得进来
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 预检要排在其它 lib 导入之前：缺源码时 `import lib.scoring` 会先炸成
# `ModuleNotFoundError`，那对人没有意义。`lib.health` 自己也可能缺，所以先兜一层；
# `lib.pack` 放到预检之后再导（预检会点名它）。
try:
    from lib.health import REQUIRED_MODULES, build_report, check_install, render_report  # noqa: E402
except ModuleNotFoundError as exc:  # 连预检模块都缺：只能直接报名字
    print(
        f"personal-gtd 安装不完整：缺少源码 {exc.name or 'lib.health'}。"
        "只有 .pyc 不可用：字节码与 Python 版本绑定，换机器/换版本就失效。"
        "请用 `gtd pack` 打源码包，解压覆盖后重装。",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


def _preflight_sources() -> None:
    """源码必须齐全：只同步到 `.pyc` 不算数（字节码与 Python 版本绑定）。

    放在所有 lib 导入之前：缺源码时 `import lib.scoring` 会先炸成
    `ModuleNotFoundError`，那对人没有意义。
    """
    lib_dir = Path(__file__).resolve().parent / "lib"
    missing, _ = check_install(lib_dir)
    if not missing:
        return
    print("personal-gtd 安装不完整：缺少源码 " + "、".join(missing), file=sys.stderr)
    print(
        "只有 .pyc 不可用：字节码与 Python 版本绑定，换机器/换版本就失效。"
        "请用 `gtd pack` 打源码包，解压覆盖后重装。",
        file=sys.stderr,
    )
    raise SystemExit(2)


_preflight_sources()

from lib.pack import build_pack, collect_files  # noqa: E402

from lib.config import (  # noqa: E402
    Config,
    DEFAULT_CONFIG_PATH,
    init_config,
    load_config,
)
from lib.dida import DidaClient, DidaError, load_dida_token  # noqa: E402
from lib.models import DayInputs, DayScore, Task  # noqa: E402
from lib.notes import (  # noqa: E402
    ENV_FNS_TOKEN,
    ENV_FNS_URL,
    ENV_VAULT_DIR,
    NotesError,
    NotesWriter,
    WriterConfigError,
    write_with_fallback,
    writer_chain,
)
from lib.report import render_monthly, render_weekly  # noqa: E402
from lib.review_note import parse_frontmatter, render_daily  # noqa: E402
from lib.scoring import (  # noqa: E402
    parse_task_points,
    task_final_points,
    task_prefill_points,
)
from lib.settle import settle_day  # noqa: E402

#: GTD 输出的固定子结构（相对 `config.gtd_dir`；由 skill 自己建，不走配置）
PLANS_SUBDIR = "1-规划"
REVIEWS_SUBDIR = "2-回顾"

#: 日回顾在回顾区下的子目录
DAILY_SUBDIR = "1-日维度"

#: `init` 在 folder 模式下补齐的回顾子目录
REVIEW_SUBDIRS = (DAILY_SUBDIR, "2-周维度", "3-月维度")

#: 文件名里的星期写法（设计稿 `review-YYYY-MM-DD-dddd.md` 的 dddd）；
#: 与正文 `{{weekday}}` 用的 `周一` 不是同一套，互不影响
FILENAME_WEEKDAYS = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)

WRITER_HINT = (
    f"未配置笔记写入后端：请设置 {ENV_FNS_URL} + {ENV_FNS_TOKEN}（FNS），"
    f"或 {ENV_VAULT_DIR}（folder）"
)

#: `--dry-run` 不读前一天账本，这些字段的起点是 0；其余字段与真实结算一致
DRY_RUN_LEDGER_HINT = (
    "提示：--dry-run 不读前一天账本，weekly_* / spent_* / unmet_* 从 0 起算；"
    "earned_* / planned_total / denominator / rate / spendable 与真实结算一致"
)

#: 读笔记的三种结果：读到 / 确实没有 / 读失败（后端故障，不能当成「没有」）
READ_OK = "ok"
READ_MISSING = "missing"
READ_FAILED = "failed"

#: 前一天没有日回顾时的提示（周账会从 0 起算，提醒用户先 backfill）
MISSING_LEDGER_HINT = (
    "前一天没有日回顾，周账从 0 起算（可先运行 `gtd backfill --from ... --to ...` 补齐）"
)

#: 没有写入后端时的一次性设置（`init` 与文档共用同一句）
def _writer_setup_hint() -> str:
    """按当前操作系统给出设置提示；不写死机器路径。"""
    if sys.platform == "win32":
        command = 'setx PERSONAL_GTD_VAULT_DIR "<vault-root>"'
    else:
        command = 'export PERSONAL_GTD_VAULT_DIR="<vault-root>"'
    return f"{command}（或设置 PERSONAL_GTD_FNS_URL + PERSONAL_GTD_FNS_TOKEN；重启 agent 生效）"


# ---------- 通用小工具 ----------


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期格式应为 YYYY-MM-DD，收到 {value!r}"
        ) from exc


def _parse_ids(value: str | None) -> set[str]:
    """把 `--late-subjective` 的逗号分隔列表折成 ID 集合；空白项丢掉。"""
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def _coerce_day(value: date | str) -> date:
    """`date` 或 `YYYY-MM-DD` 字符串统一成 `date`。

    `backfill` 按 ISO 字符串递推日期（`_settle_one` 的入参因此双形态），
    其余命令直接传 `date`。
    """
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _date_range(start: date, end: date) -> list[date]:
    """闭区间 `[start, end]` 的日期列表，升序。"""
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # 账本内部用 0/1 传真假，别让 str(1.0) == "1.0" 掉进字符串分支
        return value != 0
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _parse_number(value: object) -> float | None:
    """frontmatter 值一律是字符串；解析不出数字返回 None（对账要区分「缺」与 0）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    """与人读的 frontmatter 一样走 `:g`（22 不写成 22.0）。"""
    return f"{float(value):g}"


def _previous_from(text: str | None) -> dict[str, float]:
    """从上一份日回顾的 frontmatter 取滚动账本；缺文件/缺字段一律 0。"""
    values = parse_frontmatter(text or "")
    return {
        "spendable": _as_float(values.get("spendable")),
        "weekly_earned": _as_float(values.get("weekly_earned")),
        "weekly_spent": _as_float(values.get("weekly_spent")),
        "weekly_penalty_pending": (
            1.0 if _as_bool(values.get("weekly_penalty_pending")) else 0.0
        ),
    }


def _is_ledger(values: dict[str, object]) -> bool:
    """frontmatter 是不是本 skill 写的账本。

    `1-日维度` 里还有八篇老的自适应日总结（没有 frontmatter，或只有
    `created` / `tags`），`parse_frontmatter` 对它们返回 `{}`。把它们当成
    「工作日完成率 0」会把月完成率腰斩，所以必须要求 `date` + `earned_total`。
    """
    if not values.get("date"):
        return False
    return "earned_total" in values


def _score_payload(score: DayScore) -> dict[str, object]:
    """DayScore → 可 JSON 化的 dict（`day` 写成 `YYYY-MM-DD`，items 折成列表）。"""
    payload = asdict(score)
    payload["day"] = score.day.isoformat()
    return payload


def _review_rel_path(day: date, config: Config) -> str:
    """日回顾在 vault 里的相对路径：`<gtd_dir>/2-回顾/1-日维度/review-<日期>-<星期>.md`。"""
    root = config.gtd_dir.strip("/")
    weekday = FILENAME_WEEKDAYS[day.weekday()]
    return f"{root}/{REVIEWS_SUBDIR}/{DAILY_SUBDIR}/review-{day.isoformat()}-{weekday}.md"


def _read_note(writers: Sequence[NotesWriter], rel_path: str) -> str | None:
    """按写入链顺序读第一份拿得到的笔记；读不到或读失败都返回 None。

    只给「读不到就跳过」的调用方（`balance` / `audit` / `report`）用；
    账本滚动要区分「没有」和「读失败」，走 `_read_note_state`。
    """
    state, text = _read_note_state(writers, rel_path)
    return text if state == READ_OK else None


def _read_note_state(writers: Sequence[NotesWriter], rel_path: str) -> tuple[str, str | None]:
    """三态读笔记：`("ok", 内容)` / `("missing", None)` / `("failed", None)`。

    链上逐个后端尝试：任一后端读到内容即 `ok`；只要有一个后端抛异常
    （HTTP/本地错误，说明「读不到」不等于「没有」）就记一次失败；全部后端
    都明确返回「不存在」才算 `missing`，有失败则算 `failed`。
    """
    failed = False
    for writer in writers:
        try:
            text = writer.read(rel_path)
        except Exception:  # noqa: BLE001 - 后端故障要上报，不能当成「笔记不存在」
            failed = True
            continue
        if text is not None:
            return READ_OK, text
    return (READ_FAILED if failed else READ_MISSING), None


def _note_exists(writers: Sequence[NotesWriter], rel_path: str) -> bool:
    """保守判断笔记是否存在：任一后端读到内容就算存在，读失败也算存在。

    `backfill` 用它决定是否跳过：宁可少覆盖，也不能在读取失败时把人写的内容冲掉。
    """
    for writer in writers:
        try:
            if writer.read(rel_path) is not None:
                return True
        except Exception:  # noqa: BLE001 - 读不了就按存在处理，保护已有笔记
            return True
    return False


def _as_writers(
    writer: NotesWriter | Sequence[NotesWriter] | None,
) -> list[NotesWriter]:
    """`compute_day_score` 既收单个后端也收整条链；None 表示不读笔记。"""
    if writer is None:
        return []
    if isinstance(writer, (list, tuple)):
        return list(writer)
    return [writer]


@contextmanager
def _vault_override(vault_dir: str | None) -> Iterator[None]:
    """`--vault-dir` 临时覆盖 `PERSONAL_GTD_VAULT_DIR`，退出时还原。

    这样 `_settle_one` 不必知道 CLI 参数，`writer_chain` 仍按环境变量决策。
    """
    if not vault_dir:
        yield
        return
    previous = os.environ.get(ENV_VAULT_DIR)
    os.environ[ENV_VAULT_DIR] = str(vault_dir)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV_VAULT_DIR, None)
        else:
            os.environ[ENV_VAULT_DIR] = previous


# ---------- 取数 ----------


def _build_client(config: Config) -> DidaClient:
    token = load_dida_token(Path(config.dida_token_path))
    return DidaClient(
        token,
        base_url=config.dida_base_url,
        inbox_id=config.inbox_id,
    )


def load_day_inputs(
    client: DidaClient,
    day: date,
    *,
    late_subjective_ids: set[str],
    previous: dict[str, float],
    config: Config,
) -> DayInputs:
    """把一天的滴答数据取成 `DayInputs`。

    任务 = 未完成任务 + 当日完成记录，按 id 去重；完成记录覆盖未完成副本，
    因为只有它带 `completed_time`（结算靠它判断「今天做完了」）。
    `previous` 是前一天滚过来的账本（`spendable` / `weekly_earned` /
    `weekly_spent` / `weekly_penalty_pending`，后者用 0/1 表示真假）。
    `config` 目前只为接口定型保留，取数本身不依赖配置。
    """
    merged: dict[str, Task] = {}
    for task in client.all_open_tasks():
        merged.setdefault(task.id, task)
    for task in client.completed_tasks(day, day):
        merged[task.id] = task

    habits = tuple(client.habits())
    checkins = (
        client.habit_checkins([habit.id for habit in habits], day, day) if habits else {}
    )
    habit_values = {
        habit_id: value for (habit_id, when), value in checkins.items() if when == day
    }

    focus = tuple(client.focus(day, day, 0)) + tuple(client.focus(day, day, 1))

    return DayInputs(
        day=day,
        tasks=tuple(merged.values()),
        habits=habits,
        habit_values=habit_values,
        focus=focus,
        late_subjective_ids=frozenset(late_subjective_ids),
        previous_spendable=_as_float(previous.get("spendable", 0.0)),
        weekly_earned_before=_as_float(previous.get("weekly_earned", 0.0)),
        weekly_spent_before=_as_float(previous.get("weekly_spent", 0.0)),
        weekly_penalty_pending=_as_bool(previous.get("weekly_penalty_pending", 0.0)),
    )


def _settle_score(
    day: date,
    late_subjective_ids: set[str],
    previous: dict[str, float],
    config: Config,
) -> DayScore:
    client = _build_client(config)
    inputs = load_day_inputs(
        client,
        day,
        late_subjective_ids=late_subjective_ids,
        previous=previous,
        config=config,
    )
    return settle_day(inputs, config)


# ---------- score ----------


def _cmd_score(args: argparse.Namespace) -> int:
    task = Task(
        id="cli",
        project_id="",
        project_name="",
        title=args.title,
        priority=args.priority,
    )
    # 预填口径：标题有 $N 时 N 胜出；否则 优先级底分 × 规模系数
    effective = task_prefill_points(task, args.size)
    final_points, late = task_final_points(
        task,
        late_subjective=args.late_subjective,
        breakthrough=args.breakthrough,
        points=effective,
    )
    payload = {
        "explicit_points": parse_task_points(task.title),
        "effective_points": effective,
        "final_points": final_points,
        "late": late,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _previous_ledger(
    day: date,
    writers: Sequence[NotesWriter],
    config: Config,
) -> dict[str, float]:
    """前一天滚过来的账本；周一强制把周账与待罚清零（周日那条的 spendable 仍保留）。

    读笔记是**三态**的：`missing` 只提示「周账从 0 起算」，`failed`（后端/HTTP
    故障）直接抛 `NotesError`——把读失败当成「没有」会把周账静默清零并写进账本。
    没有后端（`settle --dry-run` / `audit` 不读账本）时按 0，且不提示。
    """
    if not writers:
        previous = _previous_from(None)
    else:
        rel_path = _review_rel_path(day - timedelta(days=1), config)
        state, text = _read_note_state(writers, rel_path)
        if state == READ_FAILED:
            raise NotesError(
                f"读取前一天的日回顾失败：{rel_path}；"
                "周账无法滚动，本次未写入（先检查笔记后端再重跑）"
            )
        if state == READ_MISSING:
            print(MISSING_LEDGER_HINT, file=sys.stderr)
        previous = _previous_from(text)
    if day.weekday() == 0:
        # 周一：周账强制归零；previous_spendable 仍取周日的
        previous["weekly_earned"] = 0.0
        previous["weekly_spent"] = 0.0
        previous["weekly_penalty_pending"] = 0.0
    return previous


def compute_day_score(
    day: date | str,
    *,
    late_subjective_ids: set[str],
    writer: NotesWriter | Sequence[NotesWriter] | None,
    config: Config | None = None,
) -> DayScore:
    """重算某天的 `DayScore`（`audit` 的重算入口，也是 `_settle_one` 的内核）。

    `writer` 用来读前一天日回顾的滚动账本，单个后端或整条链都行；
    传 `None`（或不传后端）时账本全按 0，等价于 `settle --dry-run` 的口径。
    `config` 只为免去调用方重复 `load_config`，不给就现读。
    """
    settled_day = _coerce_day(day)
    cfg = load_config() if config is None else config
    previous = _previous_ledger(settled_day, _as_writers(writer), cfg)
    return _settle_score(settled_day, set(late_subjective_ids), previous, cfg)


# ---------- settle ----------


def _settle_one(
    day: date | str,
    dry_run: bool,
    *,
    late_subjective_ids: set[str] | frozenset[str] = frozenset(),
    force: bool = False,
) -> int:
    """结算一天并写入日回顾；返回退出码。

    `dry_run` 不读笔记、不碰 `writer_chain`，只打印 `DayScore` JSON。
    真实写入时，目标日回顾已存在就拒绝（正文里有人写的总结/确认/谋划/身份反馈，
    整篇重写会冲掉），只有 `--force` 才覆盖——更正账本时先读旧内容再加 `--force`。
    `settle` 与 `backfill` 共用这一条路径，规则不复制。
    """
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    try:
        settled_day = _coerce_day(day)
        ids = set(late_subjective_ids)

        if dry_run:
            # 不读笔记、不碰 writer_chain：账本全按 0，结果只打印
            score = compute_day_score(
                settled_day,
                late_subjective_ids=ids,
                writer=None,
                config=config,
            )
            print(json.dumps(_score_payload(score), ensure_ascii=False))
            return 0

        rel_path = _review_rel_path(settled_day, config)
        writers = writer_chain(config.vault)
        if not force:
            state, _text = _read_note_state(writers, rel_path)
            if state == READ_FAILED:
                print(
                    f"读取 {rel_path} 失败，无法确认是否会覆盖人写的内容；本次未写入",
                    file=sys.stderr,
                )
                return 1
            if state == READ_OK:
                print(f"已存在 {rel_path}；如需覆盖请加 --force", file=sys.stderr)
                return 1
        score = compute_day_score(
            settled_day,
            late_subjective_ids=ids,
            writer=writers,
            config=config,
        )
        used = write_with_fallback(writers, rel_path, render_daily(score))
        print(f"已写入 {rel_path}（{used}）")
        print(json.dumps(_score_payload(score), ensure_ascii=False))
        return 0
    except DidaError as exc:
        print(f"滴答 API 失败：{exc}", file=sys.stderr)
        return 1
    except WriterConfigError:
        print(WRITER_HINT, file=sys.stderr)
        return 1
    except NotesError as exc:
        print(f"笔记读写失败：{exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"结算失败：{exc}", file=sys.stderr)
        return 1


def _cmd_settle(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(DRY_RUN_LEDGER_HINT, file=sys.stderr)
    with _vault_override(getattr(args, "vault_dir", None)):
        return _settle_one(
            args.date,
            args.dry_run,
            late_subjective_ids=_parse_ids(args.late_subjective),
            force=args.force,
        )


# ---------- balance ----------

#: `balance` 从两份账本里取的字段（当日那份 = 结出来的明日额度）
BALANCE_FIELDS = ("spendable", "weekly_balance", "spent_daily", "spent_weekly")


def _balance_line(label: str, value: float | None, source: str) -> str:
    shown = "未知" if value is None else f"{_format_number(value)} 分"
    return f"{label}：{shown}（{source}）"


def _cmd_balance(args: argparse.Namespace) -> int:
    """`balance --date D`：今天能花多少 + D 结算后明天能花多少。

    `spendable` 写在**当天**的 frontmatter 里，含义是**次日**额度（消费扣的是
    `previous_spendable`）。所以「今天能花多少」必须读**前一天**的账本——
    当天还没结算时也要能答，这是这个命令最常见的用法。
    """
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    day = args.date
    previous_day = day - timedelta(days=1)
    prev_rel = _review_rel_path(previous_day, config)
    day_rel = _review_rel_path(day, config)

    try:
        with _vault_override(args.vault_dir):
            writers = writer_chain(config.vault)
            prev_state, prev_text = _read_note_state(writers, prev_rel)
            day_state, day_text = _read_note_state(writers, day_rel)
    except WriterConfigError:
        print(WRITER_HINT, file=sys.stderr)
        return 1
    except NotesError as exc:
        print(f"笔记读写失败：{exc}", file=sys.stderr)
        return 1

    if READ_FAILED in (prev_state, day_state):
        broken = prev_rel if prev_state == READ_FAILED else day_rel
        print(
            f"读取 {broken} 失败：余额无法确认（故障不等于「没有」），先检查笔记后端",
            file=sys.stderr,
        )
        return 1

    prev_values = parse_frontmatter(prev_text or "")
    day_values = parse_frontmatter(day_text or "")
    prev_is_ledger = prev_state == READ_OK and _is_ledger(prev_values)
    day_is_ledger = day_state == READ_OK and _is_ledger(day_values)

    if not prev_is_ledger and not day_is_ledger:
        print(
            f"{day.isoformat()} 与前一天 {previous_day.isoformat()} 都没有日回顾："
            f"先运行 `gtd settle --date {previous_day.isoformat()}`，"
            f"再运行 `gtd settle --date {day.isoformat()}`",
            file=sys.stderr,
        )
        return 1

    today_pool = _parse_number(prev_values.get("spendable")) if prev_is_ledger else None
    tomorrow_pool = _parse_number(day_values.get("spendable")) if day_is_ledger else None

    # 周账与消费取「更新的那一份」：当日账本优先，退回前一天
    source_values = day_values if day_is_ledger else prev_values
    source_day = day if day_is_ledger else previous_day

    print(f"{day.isoformat()} 余额")
    print(
        _balance_line(
            "今日可花",
            today_pool,
            f"来自 {previous_day.isoformat()} 的日回顾" if prev_is_ledger
            else f"{previous_day.isoformat()} 没有日回顾",
        )
    )
    print(
        _balance_line(
            "明日可花",
            tomorrow_pool,
            f"{day.isoformat()} 结算后" if day_is_ledger
            else f"{day.isoformat()} 还没结算",
        )
    )
    for key, label in (
        ("weekly_balance", "周余额"),
        ("spent_daily", "日账消费"),
        ("spent_weekly", "周账消费"),
    ):
        number = _parse_number(source_values.get(key))
        print(f"{label}：{'0' if number is None else _format_number(number)} 分")
    if source_day != day:
        print(f"（周账与消费取自 {source_day.isoformat()} 的日回顾）", file=sys.stderr)
    return 0


# ---------- backfill ----------


def _cmd_backfill(args: argparse.Namespace) -> int:
    if args.end < args.start:
        print(
            f"--from 晚于 --to：{args.start.isoformat()} > {args.end.isoformat()}",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(DRY_RUN_LEDGER_HINT, file=sys.stderr)

    days = _date_range(args.start, args.end)
    failed = 0
    skipped = 0
    with _vault_override(args.vault_dir):
        try:
            writers: list[NotesWriter] = writer_chain(config.vault)
        except WriterConfigError:
            # dry-run 不需要后端；无法判断存在性时按「都不存在」预览
            if not args.dry_run:
                print(WRITER_HINT, file=sys.stderr)
                return 1
            writers = []

        for day in days:
            rel_path = _review_rel_path(day, config)
            # 默认只补缺失：日回顾正文有人写的总结/确认/谋划，不能被重算冲掉
            if not args.force and _note_exists(writers, rel_path):
                print(f"跳过 {day.isoformat()}：{rel_path} 已存在（--force 覆盖）")
                skipped += 1
                continue
            # 升序处理：每天的日回顾写完，次日 `_settle_one` 就能读到前一天账本
            if _settle_one(day.isoformat(), args.dry_run, force=args.force) != 0:
                failed += 1

    succeeded = len(days) - skipped - failed
    print(f"backfill：{len(days)} 天，成功 {succeeded}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


# ---------- audit ----------

#: 对账字段：重算值 vs frontmatter（含周账三个数，用于查「余额异常」）
AUDIT_FIELDS = (
    "earned_total",
    "denominator",
    "rate",
    "spendable",
    "weekly_earned",
    "weekly_spent",
    "weekly_balance",
)

#: 日回顾里有主观超时折扣、但没给 `--late-subjective` 时的提示
LATE_HINT = "该日有主观超时折扣；请用 --late-subjective 复核"


#: `rate` 在 frontmatter 里固定 3 位小数；其余数值走 `:g`（6 位有效数字），
#: 1.8333333… 落盘成 1.83333。对账容差必须覆盖这次舍入，否则带惩罚（÷3）的
#: 日子永远「对不上」，反过来会诱导人去改一个本来正确的账本。
_RATE_DECIMALS = 3
_RENDER_REL_TOL = 1e-5
_ABS_TOL = 1e-6


def _same_number(key: str, expected: float, actual: float | None) -> bool:
    """`rate` 按 3 位小数比，其余按 abs 1e-6 / rel 1e-5 容差；缺值不算一致。"""
    if actual is None:
        return False
    expected = float(expected)
    if key == "rate":
        return round(expected, _RATE_DECIMALS) == round(actual, _RATE_DECIMALS)
    return abs(expected - actual) <= max(_ABS_TOL, abs(expected) * _RENDER_REL_TOL)


def _audit_one_day(
    day: date,
    writers: Sequence[NotesWriter],
    config: Config,
    late_subjective_ids: set[str] | None = None,
) -> int:
    """对账一天，返回不一致处数；缺日回顾 / 不是账本笔记也算一处。"""
    ids = set(late_subjective_ids or ())
    rel_path = _review_rel_path(day, config)
    text = _read_note(writers, rel_path)
    if text is None:
        print(f"{day.isoformat()} {rel_path}：缺日回顾（未结算）")
        return 1

    values = parse_frontmatter(text)
    if not _is_ledger(values):
        print(f"{day.isoformat()} {rel_path}：不是账本笔记，已跳过")
        return 1

    score = compute_day_score(
        day,
        late_subjective_ids=ids,
        writer=writers,
        config=config,
    )
    mismatches = 0
    # 折扣是结算时按当次确认算的，重算必须拿到同一份 ID 列表才能对上
    if not ids and _as_float(values.get("late_discount")) > 0:
        print(f"{day.isoformat()} {rel_path}：{LATE_HINT}")
    for key in AUDIT_FIELDS:
        expected = float(getattr(score, key))
        raw = values.get(key)
        if _same_number(key, expected, _parse_number(raw)):
            continue
        mismatches += 1
        shown = "（缺失）" if raw is None else str(raw)
        expected_text = _format_number(expected)
        print(f"{day.isoformat()} {key}：frontmatter {shown} ≠ 重算 {expected_text}")
    return mismatches


def _cmd_audit(args: argparse.Namespace) -> int:
    if args.date is not None and (args.start is not None or args.end is not None):
        print("audit 的 --date 与 --from/--to 不能同时给", file=sys.stderr)
        return 2
    if args.date is not None:
        days = [args.date]
    elif args.start is None or args.end is None or args.end < args.start:
        print(
            "audit 需要 --date，或成对的 --from/--to（且 --from 不晚于 --to）",
            file=sys.stderr,
        )
        return 2
    else:
        days = _date_range(args.start, args.end)

    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    mismatches = 0
    ids = _parse_ids(getattr(args, "late_subjective", ""))
    try:
        with _vault_override(args.vault_dir):
            writers = writer_chain(config.vault)
            for day in days:
                mismatches += _audit_one_day(day, writers, config, ids)
    except WriterConfigError:
        print(WRITER_HINT, file=sys.stderr)
        return 1
    except NotesError as exc:
        print(f"笔记读写失败：{exc}", file=sys.stderr)
        return 1
    except DidaError as exc:
        print(f"滴答 API 失败：{exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"对账失败：{exc}", file=sys.stderr)
        return 1

    if mismatches:
        print(f"对账失败：{len(days)} 天，{mismatches} 处不一致")
        return 1
    print(f"对账通过：{len(days)} 天一致")
    return 0


# ---------- report / monthly ----------


def _parse_month(value: str) -> date:
    """`YYYY-MM` → 该月 1 号（argparse 类型）。"""
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"月份格式应为 YYYY-MM，收到 {value!r}"
        ) from exc


def _month_days(first: date) -> list[date]:
    """该月全部日期（升序）。"""
    last_day = calendar.monthrange(first.year, first.month)[1]
    return _date_range(first, date(first.year, first.month, last_day))


def _load_day_frontmatter(
    days: Sequence[date],
    config: Config,
    vault_dir: str | None,
) -> tuple[list[dict[str, object]], list[date]]:
    """读区间内每天的日回顾 frontmatter；缺的、不是账本的都算 `missing`。

    `1-日维度` 里还有老的自适应日总结，它们的 frontmatter 解析出来是 `{}`；
    当成「完成率 0」会把统计拉垮，所以只接受带 `date` + `earned_total` 的账本，
    其余按「跳过」处理并说明原因。

    **读失败**（后端/HTTP 故障）直接抛 `NotesError`，不并入 `missing`——
    「读不到」不等于「没有」，报表不能基于静默残缺的数据。
    """
    values: list[dict[str, object]] = []
    missing: list[date] = []
    with _vault_override(vault_dir):
        writers = writer_chain(config.vault)
        for day in days:
            rel_path = _review_rel_path(day, config)
            state, text = _read_note_state(writers, rel_path)
            if state == READ_FAILED:
                # 后端故障不能报成「没有账本」：月金额要换真钱，静默偏低最危险
                raise NotesError(
                    f"读取 {rel_path} 失败；报表不能基于残缺数据生成"
                    "（先检查笔记后端再重跑）"
                )
            if text is None:
                missing.append(day)
                continue
            day_values = parse_frontmatter(text)
            if not _is_ledger(day_values):
                print(f"{day.isoformat()} {rel_path}：不是账本笔记，已跳过", file=sys.stderr)
                missing.append(day)
                continue
            values.append(day_values)
    return values, missing


def _read_report_days(
    days: Sequence[date],
    config: Config,
    vault_dir: str | None,
) -> tuple[list[dict[str, object]], list[date]] | None:
    """带错误处理的读日回顾；配置/笔记出错时打印原因并返回 None。"""
    try:
        return _load_day_frontmatter(days, config, vault_dir)
    except WriterConfigError:
        print(WRITER_HINT, file=sys.stderr)
    except NotesError as exc:
        print(f"笔记读写失败：{exc}", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(f"读取日回顾失败：{exc}", file=sys.stderr)
    return None


def _warn_missing(missing: Sequence[date]) -> None:
    if missing:
        print(
            f"提示：{len(missing)} 天没有账本笔记"
            "（未结算，或不是本 skill 写的日回顾），已跳过",
            file=sys.stderr,
        )


def cmd_report(args: argparse.Namespace) -> int:
    """`report --from --to`：读区间日回顾，打印周/区间回顾 Markdown（不写文件）。"""
    if args.end < args.start:
        print(
            f"--from 晚于 --to：{args.start.isoformat()} > {args.end.isoformat()}",
            file=sys.stderr,
        )
        return 2

    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    loaded = _read_report_days(
        _date_range(args.start, args.end), config, args.vault_dir
    )
    if loaded is None:
        return 1

    values, missing = loaded
    if not values:
        print(
            f"{args.start.isoformat()} ~ {args.end.isoformat()} 没有日回顾："
            f"先运行 `gtd settle` 或 `gtd backfill`",
            file=sys.stderr,
        )
        return 1

    print(render_weekly(values, start=args.start, end=args.end))
    _warn_missing(missing)
    return 0


def cmd_monthly(args: argparse.Namespace) -> int:
    """`monthly --month YYYY-MM`：读该月日回顾，打印完成率、金额、工资、门槛。"""
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    first = args.month
    month = f"{first.year:04d}-{first.month:02d}"
    loaded = _read_report_days(_month_days(first), config, args.vault_dir)
    if loaded is None:
        return 1

    values, missing = loaded
    if not values:
        print(f"{month} 没有日回顾：先运行 `gtd backfill --from ... --to ...`", file=sys.stderr)
        return 1

    if config.salary <= 0:
        print("提示：未配置 salary，本月金额按 0 计", file=sys.stderr)

    print(
        render_monthly(
            values,
            month=month,
            salary=config.salary,
            threshold=config.month_threshold,
            budget_rate=config.month_budget_rate,
        )
    )
    _warn_missing(missing)
    return 0


# ---------- init ----------


def _writer_mode_lines() -> list[str]:
    """报告当前 writer 组合，并点名缺哪个环境变量。"""
    url = (os.environ.get(ENV_FNS_URL) or "").strip()
    token = (os.environ.get(ENV_FNS_TOKEN) or "").strip()
    folder = (os.environ.get(ENV_VAULT_DIR) or "").strip()

    fns_ready = bool(url and token)
    if fns_ready and folder:
        mode = "FNS（folder 兜底）"
    elif fns_ready:
        mode = "FNS"
    elif folder:
        mode = "folder"
    else:
        mode = "未配置"

    lines = [f"writer：{mode}"]
    if mode == "未配置":
        lines.append(
            "  未配置：现在还不能写入（settle / balance / backfill / audit / report / "
            "monthly 都会退出 1；只有 score、settle --dry-run、init 可用）"
        )
        lines.append(f"  一次性设置：{_writer_setup_hint()}")
    if fns_ready:
        lines.append(f"  FNS：已配置（{ENV_FNS_URL}、{ENV_FNS_TOKEN}）")
    else:
        missing = [
            name
            for name, value in ((ENV_FNS_URL, url), (ENV_FNS_TOKEN, token))
            if not value
        ]
        lines.append(f"  FNS：缺 {', '.join(missing)}")
    if folder:
        lines.append(f"  folder：已配置（{ENV_VAULT_DIR}）")
    else:
        lines.append(f"  folder：缺 {ENV_VAULT_DIR}")
    return lines


def _version_line(label: str, argv: list[str] | None) -> str:
    if argv is None:
        return f"{label}：未安装（PATH 中找不到）"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{label}：检查失败（{exc}）"
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    first = text.splitlines()[0] if text else f"退出码 {proc.returncode}"
    return f"{label}：{first}"


def _ensure_review_dirs(config: Config) -> list[str]:
    """folder 模式下补齐 `2-回顾` 的三个维度目录；返回要打印的行。

    设计稿把 `init` 定义为「配置、目录、检查环境」。目录只在有
    `PERSONAL_GTD_VAULT_DIR` 时创建：FNS 后端的 vault 在服务端，本地建目录没有意义。
    已存在的目录不报错（幂等），逐个列出「新建 / 已存在」。
    """
    folder = (os.environ.get(ENV_VAULT_DIR) or "").strip()
    if not folder:
        url = (os.environ.get(ENV_FNS_URL) or "").strip()
        token = (os.environ.get(ENV_FNS_TOKEN) or "").strip()
        if url and token:
            return ["回顾目录：FNS 模式，跳过本地目录创建"]
        return [f"回顾目录：缺 {ENV_VAULT_DIR}，跳过目录创建"]

    base = Path(folder) / config.gtd_dir.strip("/")
    created: list[str] = []
    existed: list[str] = []

    def _ensure(rel: str) -> None:
        target = base / rel
        if target.is_dir():
            existed.append(rel)
        else:
            target.mkdir(parents=True, exist_ok=True)
            created.append(rel)

    _ensure(PLANS_SUBDIR)
    _ensure(REVIEWS_SUBDIR)
    for name in REVIEW_SUBDIRS:
        _ensure(f"{REVIEWS_SUBDIR}/{name}")

    lines = [f"GTD 目录：{base}"]
    if created:
        lines.append(f"  新建：{', '.join(created)}")
    if existed:
        lines.append(f"  已存在：{', '.join(existed)}")
    return lines


def _cmd_init(_args: argparse.Namespace) -> int:
    try:
        config = init_config()
    except (OSError, ValueError) as exc:
        print(f"配置初始化失败：{exc}", file=sys.stderr)
        return 1

    print(f"配置文件：{config.config_path}")
    print(f"GTD 根目录：{config.gtd_dir}（相对 vault 根）")
    print(f"理论目录：{config.theory_dir}（相对 vault 根；读方法论原文用）")
    for line in _writer_mode_lines():
        print(line)
    try:
        for line in _ensure_review_dirs(config):
            print(line)
    except OSError as exc:
        print(f"回顾目录创建失败：{exc}", file=sys.stderr)
        return 1
    print(_version_line("python", [sys.executable, "--version"]))
    dida = shutil.which("dida")
    print(_version_line("dida", [dida, "--version"] if dida else None))
    if not dida:
        print("  安装：npm i -g @suibiji/dida-cli（Node >= 20）")
    return 0


def _cmd_selfcheck(args: argparse.Namespace) -> int:
    """检查安装完整性：源码齐不齐、滴答在不在、写入后端配没配。

    退出码 0 = 源码齐全（其余只算提示）；1 = 有模块缺源码，装出来是残的。
    """
    lib_dir = (
        Path(args.lib_dir)
        if args.lib_dir
        else Path(__file__).resolve().parent / "lib"
    )
    config = load_config()
    report = build_report(
        lib_dir,
        env=os.environ,
        which=shutil.which,
        dida_token_path=Path(config.dida_token_path),
    )
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "python_version": report.python_version,
                    "lib_dir": report.lib_dir,
                    "writer": report.writer,
                    "gtd_dir": config.gtd_dir,
                    "theory_dir": config.theory_dir,
                    "dida_installed": report.dida_installed,
                    "dida_token_found": report.dida_token_found,
                    "missing_sources": list(report.missing_sources),
                    "stray_bytecode": list(report.stray_bytecode),
                    "problems": list(report.problems),
                    "warnings": list(report.warnings),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_report(report))
        print(f"GTD 根目录：{config.gtd_dir}（相对 vault 根）")
        print(f"理论目录：{config.theory_dir}（相对 vault 根；读方法论原文用）")
    return 0 if report.ok else 1


def _cmd_pack(args: argparse.Namespace) -> int:
    """打出跨机器安装用的源码包：只有源码，没有字节码。"""
    root = (
        Path(args.root)
        if args.root
        else Path(__file__).resolve().parent.parent
    )
    out = (
        Path(args.out)
        if args.out
        else Path.cwd() / f"personal-gtd-{date.today():%Y%m%d}.zip"
    )
    if args.list:
        kept, skipped = collect_files(root)
        for rel in kept:
            print(rel)
        print(f"--- 排除 {len(skipped)} 个（__pycache__ / *.pyc 等）---")
        return 0
    result = build_pack(root, out, name=args.name)
    print(f"已打包：{result.archive}")
    print(f"文件 {len(result.files)} 个；排除 {len(result.skipped)} 个（__pycache__ / *.pyc 等）")
    print("解包后把 personal-gtd/ 放进 agent 的 skills 目录，再跑 `gtd selfcheck` 验一下。")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    """导出脱敏后的公开版 skill 源码树。

    自查不通过（还残留敏感片段）就不写任何东西，直接退出 1。

    `lib.publish` 只存在于私有构建里（它的规则表是私密信息），公开版没有这个命令。
    """
    try:
        from lib.publish import publish as publish_skill
    except ImportError:
        print(
            "此构建不含 publish（公开版不需要导出功能）。", file=sys.stderr
        )
        return 1
    source = (
        Path(args.source)
        if args.source
        else Path(__file__).resolve().parent.parent
    )
    try:
        result = publish_skill(source, Path(args.out))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"已导出：{result.out_dir}")
    print(f"文件 {len(result.written)} 个；清理旧的 {len(result.removed)} 个")
    print("已排除：" + "、".join(result.excluded))
    print("下一步：在这个目录里 git init、提交、推到你自己的 GitHub 仓库。")
    return 0


# ---------- 入口 ----------


def _add_vault_dir(parser: argparse.ArgumentParser) -> None:
    """碰笔记的子命令共用：`--vault-dir` 临时覆盖 `PERSONAL_GTD_VAULT_DIR`。"""
    parser.add_argument(
        "--vault-dir",
        default=None,
        metavar="DIR",
        help=f"临时覆盖 {ENV_VAULT_DIR}（folder 后端；仅本次命令生效）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtd",
        description="personal-gtd：滴答计分与日回顾结算。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="按标题、优先级与规模算一条任务的分数")
    score.add_argument("--title", required=True, help="任务标题，末尾 $N 是显式标价")
    score.add_argument("--priority", type=int, default=3, help="滴答优先级，默认 3")
    score.add_argument(
        "--size",
        choices=("S", "M", "L"),
        default="S",
        help="规模系数：S=1、M=1.5、L=2（无显式 $N 时乘优先级底分；默认 S）",
    )
    score.add_argument(
        "--late-subjective", action="store_true", help="主观认定逾期（非突破任务减半）"
    )
    score.add_argument("--breakthrough", action="store_true", help="突破任务，不打折")
    score.set_defaults(func=_cmd_score)

    settle = sub.add_parser("settle", help="结算一天并写入日回顾")
    settle.add_argument(
        "--date",
        type=_parse_date,
        default=date.today(),
        help="结算日期 YYYY-MM-DD，默认今天",
    )
    settle.add_argument(
        "--dry-run", action="store_true", help="只打印 DayScore JSON，不读不写笔记"
    )
    settle.add_argument(
        "--late-subjective",
        default="",
        metavar="IDS",
        help="主观逾期的任务 ID，逗号分隔",
    )
    settle.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的日回顾（默认拒绝，保护人写的正文）",
    )
    _add_vault_dir(settle)
    settle.set_defaults(func=_cmd_settle)

    balance = sub.add_parser("balance", help="查看某天的可花分与日/周余额")
    balance.add_argument(
        "--date",
        type=_parse_date,
        default=date.today(),
        help="查询日期 YYYY-MM-DD，默认今天",
    )
    _add_vault_dir(balance)
    balance.set_defaults(func=_cmd_balance)

    backfill = sub.add_parser("backfill", help="按日期升序补齐缺失的日回顾（默认跳过已存在，--force 覆盖）")
    backfill.add_argument(
        "--from", dest="start", type=_parse_date, required=True, help="起始日期 YYYY-MM-DD"
    )
    backfill.add_argument(
        "--to", dest="end", type=_parse_date, required=True, help="结束日期 YYYY-MM-DD（含）"
    )
    backfill.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印每天 DayScore JSON，不写笔记（不跨天滚动账本）",
    )
    backfill.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的日回顾（默认跳过，保护人写的内容）",
    )
    _add_vault_dir(backfill)
    backfill.set_defaults(func=_cmd_backfill)

    audit = sub.add_parser("audit", help="用滴答重算，与日回顾 frontmatter 对账")
    audit.add_argument("--date", type=_parse_date, default=None, help="对账单日 YYYY-MM-DD")
    audit.add_argument(
        "--from", dest="start", type=_parse_date, default=None, help="起始日期 YYYY-MM-DD"
    )
    audit.add_argument(
        "--to", dest="end", type=_parse_date, default=None, help="结束日期 YYYY-MM-DD（含）"
    )
    audit.add_argument(
        "--late-subjective",
        default="",
        metavar="IDS",
        help="结算时确认过的主观逾期任务 ID，逗号分隔（重算要用同一份）",
    )
    _add_vault_dir(audit)
    audit.set_defaults(func=_cmd_audit)

    report = sub.add_parser(
        "report", help="汇总一段时间的日回顾，打印周/区间回顾 Markdown（不写文件）"
    )
    report.add_argument(
        "--from", dest="start", type=_parse_date, required=True, help="起始日期 YYYY-MM-DD"
    )
    report.add_argument(
        "--to", dest="end", type=_parse_date, required=True, help="结束日期 YYYY-MM-DD（含）"
    )
    _add_vault_dir(report)
    report.set_defaults(func=cmd_report)

    monthly = sub.add_parser(
        "monthly", help="汇总一个月的日回顾，打印月完成率与金额（不写文件）"
    )
    monthly.add_argument(
        "--month",
        type=_parse_month,
        required=True,
        metavar="YYYY-MM",
        help="月份 YYYY-MM",
    )
    _add_vault_dir(monthly)
    monthly.set_defaults(func=cmd_monthly)

    init = sub.add_parser("init", help="初始化配置并检查环境")
    init.set_defaults(func=_cmd_init)

    selfcheck = sub.add_parser(
        "selfcheck", help="检查安装是否完整（源码、滴答、写入后端）"
    )
    selfcheck.add_argument(
        "--lib-dir", default=None, metavar="DIR", help="检查别的目录（测试用）"
    )
    selfcheck.add_argument("--json", action="store_true", help="输出 JSON")
    selfcheck.set_defaults(func=_cmd_selfcheck)

    pack = sub.add_parser(
        "pack", help="打出跨机器安装用的源码包（zip，不含字节码）"
    )
    pack.add_argument(
        "--root", default=None, metavar="DIR", help="skill 根目录，默认是本 skill 所在目录"
    )
    pack.add_argument("--out", default=None, metavar="FILE", help="输出 zip 路径")
    pack.add_argument("--name", default="personal-gtd", help="包内顶层目录名")
    pack.add_argument("--list", action="store_true", help="只列文件清单，不打包")
    pack.set_defaults(func=_cmd_pack)

    publish = sub.add_parser(
        "publish", help="导出脱敏后的公开版 skill 源码树（不含账号/路径等私密信息）"
    )
    publish.add_argument("--out", required=True, metavar="DIR", help="输出目录")
    publish.add_argument(
        "--source", default=None, metavar="DIR", help="源 skill 目录，默认是本 skill 所在目录"
    )
    publish.set_defaults(func=_cmd_publish)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

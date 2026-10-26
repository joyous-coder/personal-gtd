# tests/test_settle_cli.py
"""`settle` 的 CLI 级测试：覆盖保护（--force）、三态读账本、正常滚动与周一归零。

全部走真实的 `_settle_one` / `compute_day_score` / `load_day_inputs`，只替换
滴答客户端与 `writer_chain`，因此「读前一天 frontmatter → 结算 → 渲染 → 写笔记」
这条主链是被真正执行的。
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gtd
from lib.config import Config
from lib.models import Habit, Task
from lib.notes import FolderWriter, NotesError
from lib.review_note import parse_frontmatter

TZ8 = timezone(timedelta(hours=8))
CFG = Config()
SUNDAY = date(2026, 10, 25)
MONDAY = date(2026, 10, 26)


def note_path(day):
    return gtd._review_rel_path(day, CFG)


def ledger_note(**values):
    """拼一份最小账本 frontmatter（`date` + `earned_total` 是账本判据）。"""
    lines = ["---", f"date: {values.pop('date')}", f"earned_total: {values.pop('earned_total', 0)}"]
    lines += [f"{key}: {value}" for key, value in values.items()]
    lines += ["---", ""]
    return "\n".join(lines)


class FakeClient:
    """只实现 `load_day_inputs` 用到的读接口，不碰网络。"""

    def __init__(self, tasks=(), habits=(), checkins=None):
        self._tasks = tuple(tasks)
        self._habits = tuple(habits)
        self._checkins = dict(checkins or {})

    def all_open_tasks(self):
        return list(self._tasks)

    def completed_tasks(self, start, end):
        return [
            task
            for task in self._tasks
            if task.completed_time is not None
            and start <= task.completed_time.date() <= end
        ]

    def habits(self):
        return list(self._habits)

    def habit_checkins(self, ids, start, end):
        return dict(self._checkins)

    def focus(self, start, end, focus_type):
        return []


class FailingWriter:
    """读取指定路径时抛错，其余委托给 folder（模拟 FNS 挂了）。"""

    def __init__(self, root, fail_marker):
        self.folder = FolderWriter(Path(root))
        self.fail_marker = fail_marker
        self.writes = []

    def read(self, rel_path):
        if self.fail_marker in rel_path:
            raise NotesError("backend down")
        return self.folder.read(rel_path)

    def write(self, rel_path, content, create_only=False):
        self.writes.append(rel_path)
        self.folder.write(rel_path, content, create_only=create_only)

    def delete(self, rel_path):
        self.folder.delete(rel_path)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = gtd.main(argv)
    return code, out.getvalue(), err.getvalue()


def task(id, title, day, due_hour=9, done_hour=9, priority=3):
    return Task(
        id=id,
        project_id="p",
        project_name="P",
        title=title,
        priority=priority,
        due_date=datetime(day.year, day.month, day.day, due_hour, tzinfo=TZ8),
        completed_time=datetime(day.year, day.month, day.day, done_hour, tzinfo=TZ8),
    )


class SettleCase(unittest.TestCase):
    """共用：临时 vault + 假滴答客户端 + patch 配置与后端。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = self._tmp.name
        self.folder = FolderWriter(Path(self.vault))

    def settle(self, day, client, *extra, writers=None):
        chain = writers if writers is not None else [self.folder]
        with (
            patch.object(gtd, "load_config", return_value=CFG),
            patch.object(gtd, "writer_chain", return_value=chain),
            patch.object(gtd, "_build_client", return_value=client),
        ):
            return run(
                ["settle", "--date", day.isoformat(), "--vault-dir", self.vault, *extra]
            )

    def note(self, day):
        return Path(self.vault) / note_path(day)


class TestSettleProtectsExistingNote(SettleCase):
    """settle 默认不覆盖已存在的日回顾，--force 才整篇重写，且重跑字节一致。"""

    def test_refuses_existing_note_without_force(self):
        self.folder.write(
            note_path(SUNDAY),
            "---\ndate: 2026-10-25\nearned_total: 1\n---\n\n人手写的总结\n",
        )
        before = self.note(SUNDAY).read_text(encoding="utf-8")

        code, _out, err = self.settle(SUNDAY, FakeClient())

        self.assertEqual(code, 1)
        self.assertIn("已存在", err)
        self.assertIn("--force", err)
        self.assertEqual(self.note(SUNDAY).read_text(encoding="utf-8"), before)

    def test_force_overwrites_and_is_byte_identical_on_rerun(self):
        self.folder.write(
            note_path(SUNDAY),
            "---\ndate: 2026-10-25\nearned_total: 1\n---\n\n人手写的总结\n",
        )
        client = FakeClient(
            tasks=(task("t1", "写周报 $4", SUNDAY),),
            habits=(Habit(id="h1", name="面膜 $1", goal=1),),
            checkins={("h1", SUNDAY): 1.0},
        )

        code, _out, _err = self.settle(SUNDAY, client, "--force")
        self.assertEqual(code, 0)
        first = self.note(SUNDAY).read_text(encoding="utf-8")
        self.assertNotIn("人手写的总结", first)
        self.assertIn("写周报", first)

        code, _out, _err = self.settle(SUNDAY, client, "--force")
        self.assertEqual(code, 0)
        self.assertEqual(self.note(SUNDAY).read_text(encoding="utf-8"), first)


class TestSettleLedgerReadIsTriState(SettleCase):
    """读前一天笔记失败 → 退出 1 且不写；确实没有 → 退出 0 并提示从 0 起算。"""

    def test_read_failure_aborts_without_writing(self):
        writer = FailingWriter(self.vault, note_path(date(2026, 10, 24)))

        code, _out, err = self.settle(
            SUNDAY, FakeClient(), writers=[writer]
        )

        self.assertEqual(code, 1)
        self.assertIn("读取前一天的日回顾失败", err)
        self.assertEqual(writer.writes, [])
        self.assertFalse(self.note(SUNDAY).exists())

    def test_missing_previous_note_hints_and_starts_from_zero(self):
        client = FakeClient(tasks=(task("t1", "写周报 $4", SUNDAY),))

        code, out, err = self.settle(SUNDAY, client)

        self.assertEqual(code, 0)
        self.assertIn("前一天没有日回顾，周账从 0 起算", err)
        values = parse_frontmatter(self.note(SUNDAY).read_text(encoding="utf-8"))
        self.assertEqual(values["earned_total"], "4")
        self.assertEqual(values["weekly_earned"], "4")
        self.assertIn('"weekly_earned": 4.0', out)

    def test_target_read_failure_refuses_to_write(self):
        writer = FailingWriter(self.vault, note_path(SUNDAY))

        code, _out, err = self.settle(SUNDAY, FakeClient(), writers=[writer])

        self.assertEqual(code, 1)
        self.assertIn("无法确认", err)
        self.assertEqual(writer.writes, [])


class TestNormalSettle(SettleCase):
    """主链回归：读前一天 frontmatter → 结算 → 渲染 → 写笔记；周一强制归零。"""

    def test_rolls_ledger_from_previous_frontmatter(self):
        self.folder.write(
            note_path(date(2026, 10, 24)),
            ledger_note(
                date="2026-10-24",
                earned_total=20,
                spendable=10,
                weekly_earned=20,
                weekly_spent=3,
                weekly_penalty_pending="false",
            ),
        )
        client = FakeClient(
            tasks=(task("t1", "写周报 $4", SUNDAY),),
            habits=(Habit(id="h1", name="面膜 $1", goal=1),),
            checkins={("h1", SUNDAY): 1.0},
        )

        code, out, err = self.settle(SUNDAY, client)

        self.assertEqual(code, 0)
        self.assertNotIn("前一天没有日回顾", err)
        self.assertTrue(self.note(SUNDAY).is_file())
        self.assertIn('"weekly_earned": 25.0', out)

        values = parse_frontmatter(self.note(SUNDAY).read_text(encoding="utf-8"))
        self.assertEqual(values["kind"], "weekend")
        self.assertEqual(values["earned_task"], "4")
        self.assertEqual(values["earned_habit"], "1")
        self.assertEqual(values["earned_total"], "5")
        self.assertEqual(values["planned_total"], "4")
        self.assertEqual(values["denominator"], "30")
        self.assertEqual(values["rate"], "0.167")
        self.assertEqual(values["spendable"], "0")
        # 周账滚动：周日那天的 20 / 3 带过来
        self.assertEqual(values["weekly_earned"], "25")
        self.assertEqual(values["weekly_spent"], "3")
        self.assertEqual(values["weekly_balance"], "22")

    def test_monday_resets_weekly_ledger(self):
        self.folder.write(
            note_path(SUNDAY),
            ledger_note(
                date="2026-10-25",
                earned_total=40,
                spendable=9,
                weekly_earned=40,
                weekly_spent=6,
                weekly_penalty_pending="true",
            ),
        )
        client = FakeClient(tasks=(task("t1", "写周报 $30", MONDAY),))

        code, out, err = self.settle(MONDAY, client)

        self.assertEqual(code, 0)
        self.assertNotIn("前一天没有日回顾", err)
        self.assertIn('"weekly_earned": 30.0', out)

        values = parse_frontmatter(self.note(MONDAY).read_text(encoding="utf-8"))
        self.assertEqual(values["kind"], "workday")
        self.assertEqual(values["earned_total"], "30")
        self.assertEqual(values["spendable"], "25")
        # 周一：周赚/周花/待罚清零，只剩当天的 30
        self.assertEqual(values["weekly_earned"], "30")
        self.assertEqual(values["weekly_spent"], "0")
        self.assertEqual(values["weekly_balance"], "30")
        self.assertEqual(values["weekly_penalty_pending"], "false")


class TestAuditLateSubjective(SettleCase):
    """审阅修复：审计重算不能用空 ID 列表，否则确认过折扣的日子永远对不上。"""

    def audit(self, client, *extra):
        with (
            patch.object(gtd, "load_config", return_value=CFG),
            patch.object(gtd, "writer_chain", return_value=[self.folder]),
            patch.object(gtd, "_build_client", return_value=client),
        ):
            return run(
                ["audit", "--date", SUNDAY.isoformat(), "--vault-dir", self.vault, *extra]
            )

    def test_audit_passes_with_ids_and_hints_without(self):
        # 09:00 截止、12:00 完成：客观逾期；用户确认主观后结算打 5 折
        client = FakeClient(tasks=(task("t1", "写周报 $4", SUNDAY, done_hour=12),))

        code, _out, _err = self.settle(SUNDAY, client, "--late-subjective", "t1")
        self.assertEqual(code, 0)
        values = parse_frontmatter(self.note(SUNDAY).read_text(encoding="utf-8"))
        self.assertEqual(values["earned_total"], "2")
        self.assertEqual(values["late_discount"], "2")

        code, _out, err = self.audit(client, "--late-subjective", "t1")
        self.assertEqual(code, 0, err)

        code, out, _err = self.audit(client)
        self.assertEqual(code, 1)
        self.assertIn("该日有主观超时折扣；请用 --late-subjective 复核", out)

    def test_audit_skips_legacy_note(self):
        self.folder.write(
            note_path(SUNDAY), "# 2026-10-25 星期日 日总结\n\n---\n\n## 时间管理\n"
        )

        code, out, _err = self.audit(FakeClient())

        self.assertEqual(code, 1)
        self.assertIn("不是账本笔记，已跳过", out)

    def test_audit_tolerates_frontmatter_rounding(self):
        """惩罚日 spendable = (10−5)/3 = 1.6666…，frontmatter 只存 1.66667。"""
        client = FakeClient(
            tasks=(task("t1", "写周报 $10", SUNDAY),),
            habits=(Habit(id="p1", name="惩罚习惯", goal=5),),
            checkins={("p1", SUNDAY): 1.0},
        )

        code, _out, err = self.settle(SUNDAY, client)
        self.assertEqual(code, 0, err)
        values = parse_frontmatter(self.note(SUNDAY).read_text(encoding="utf-8"))
        self.assertEqual(values["spendable"], "1.66667")

        code, out, err = self.audit(client)
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()

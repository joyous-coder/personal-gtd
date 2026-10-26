# tests/test_cli.py
import json, tempfile, unittest, sys
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gtd

class TestCli(unittest.TestCase):
    def test_score_prints_json(self):
        with patch("sys.stdout") as out:
            code = gtd.main(["score", "--title", "写周报 $4", "--priority", "5"])
        payload = json.loads("".join(c.args[0] for c in out.write.call_args_list))
        self.assertEqual(code, 0)
        self.assertEqual(payload["final_points"], 4.0)

    def test_settle_dry_run_does_not_write(self):
        from datetime import date
        from lib.models import DayInputs
        # `_build_client` 会去读真实的滴答 token 文件；测试不依赖本机环境
        with patch.object(gtd, "load_day_inputs") as load, \
             patch.object(gtd, "_build_client") as build, \
             patch.object(gtd, "writer_chain") as wc, \
             patch("sys.stdout"):
            load.return_value = DayInputs(day=date(2026,10,25), tasks=(), habits=(),
                                           habit_values={}, focus=())
            code = gtd.main(["settle", "--date", "2026-10-25", "--dry-run"])
        wc.assert_not_called()
        build.assert_called()
        self.assertEqual(code, 0)

    def test_late_subjective_parsing(self):
        self.assertEqual(gtd._parse_ids("a,b"), {"a", "b"})
        self.assertEqual(gtd._parse_ids(""), set())


class TestRenderItems(unittest.TestCase):
    """Task 6 裁定：补一条带明细的渲染测试，覆盖 _render_items / _render_consumption。"""

    def test_rendered_body_lists_item_name_and_points(self):
        from lib.models import DayScore, ItemScore
        from lib.review_note import render_daily
        score = DayScore(
            day=date(2026, 10, 25),
            items=(
                ItemScore(kind="task", id="t1", name="写周报", points=4, planned=4),
            ),
        )
        text = render_daily(score)
        lines = text.splitlines()
        body = "\n".join(lines[lines.index("---", 1) + 1:])
        self.assertIn("写周报", body)
        self.assertIn("4 分", body)
        self.assertIn("（计划 4）", body)


class TestScoreSize(unittest.TestCase):
    """审阅修复：`score` 要按规模系数（S=1 / M=1.5 / L=2）给出预填分。"""

    def _score(self, *argv):
        with patch("sys.stdout") as out:
            code = gtd.main(["score", *argv])
        self.assertEqual(code, 0)
        return json.loads("".join(c.args[0] for c in out.write.call_args_list))

    def test_size_multiplies_priority_base(self):
        payload = self._score("--title", "写周报", "--priority", "5", "--size", "L")
        self.assertIsNone(payload["explicit_points"])
        self.assertEqual(payload["effective_points"], 6.0)
        self.assertEqual(payload["final_points"], 6.0)

    def test_size_defaults_to_s(self):
        payload = self._score("--title", "写周报", "--priority", "5")
        self.assertEqual(payload["final_points"], 3.0)

    def test_size_m(self):
        payload = self._score("--title", "刷一套面试题", "--priority", "3", "--size", "M")
        self.assertEqual(payload["final_points"], 3.0)

    def test_explicit_points_win_over_size(self):
        payload = self._score("--title", "写周报 $4", "--priority", "5", "--size", "L")
        self.assertEqual(payload["explicit_points"], 4.0)
        self.assertEqual(payload["effective_points"], 4.0)
        self.assertEqual(payload["final_points"], 4.0)


class TestPreviousLedger(unittest.TestCase):
    """自审发现的回归：账本内部用 0/1 传真假，不能被 str(1.0) 误判成假。"""

    def test_previous_frontmatter_maps_numbers_and_flag(self):
        previous = gtd._previous_from(
            "---\nspendable: 22\nweekly_earned: 50\nweekly_spent: 5\n"
            "weekly_penalty_pending: true\n---\n"
        )
        self.assertEqual(previous["spendable"], 22.0)
        self.assertEqual(previous["weekly_earned"], 50.0)
        self.assertEqual(previous["weekly_spent"], 5.0)
        self.assertTrue(gtd._as_bool(previous["weekly_penalty_pending"]))
        self.assertFalse(gtd._as_bool(gtd._previous_from(None)["weekly_penalty_pending"]))

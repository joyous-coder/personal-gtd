import unittest, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.models import DayScore
from lib.review_note import render_daily, parse_frontmatter, replace_frontmatter

SCORE = DayScore(day=date(2026,10,25), kind="weekend", earned_task=18, earned_habit=9,
    earned_total=27, planned_total=52, denominator=52, rate=0.519, late_discount=1.5,
    late_pending=False, reserve=5, spendable=22, spent_daily=0, spent_weekly=0,
    unmet_minutes=0, unmet_points=0, daily_balance=22, weekly_earned=27, weekly_spent=0,
    weekly_balance=27, weekly_penalty_pending=False, penalty_applied=False, items=())

class TestRender(unittest.TestCase):
    def test_frontmatter_and_sections(self):
        text = render_daily(SCORE)
        self.assertTrue(text.startswith("---\n"))
        fm = parse_frontmatter(text)
        self.assertEqual(fm["date"], "2026-10-25")
        self.assertEqual(fm["kind"], "weekend")
        self.assertEqual(fm["rate"], "0.519")
        self.assertEqual(fm["spendable"], "22")
        self.assertIn("## 积分", text)
        self.assertIn("明日可花", text)

    def test_replace_frontmatter(self):
        text = "---\ndate: 2026-10-25\nrate: 0.1\n---\n# x\n"
        out = replace_frontmatter(text, {"rate": "0.2", "late_pending": "true"})
        fm = parse_frontmatter(out)
        self.assertEqual(fm["rate"], "0.2")
        self.assertEqual(fm["late_pending"], "true")
        self.assertIn("# x", out)

# tests/test_report.py
import unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.report import monthly_summary, weekly_summary

def d(date, kind, earned, planned, denom, rate, penalty=False):
    return {"date": date, "kind": kind, "earned_total": earned, "planned_total": planned,
            "denominator": denom, "rate": rate, "penalty_applied": penalty}

class TestMonthly(unittest.TestCase):
    def test_weekday_and_weekend_average(self):
        days = [d("2026-10-23","workday",30,50,50,0.6),
                d("2026-10-24","weekend",20,20,20,1.0),
                d("2026-10-25","weekend",10,20,20,0.5)]
        r = monthly_summary(days, salary=10000, threshold=0.6, budget_rate=0.1)
        self.assertAlmostEqual(r["weekday_rate"], 0.6)
        self.assertAlmostEqual(r["weekend_rate"], 0.75)  # (20+10) / min(60,max(30,20+20)) = 30/40
        self.assertAlmostEqual(r["overall_rate"], 0.675)
        self.assertAlmostEqual(r["money"], 675.0)

    def test_below_threshold_zero(self):
        days = [d("2026-10-23","workday",10,50,50,0.2)]
        r = monthly_summary(days, salary=10000, threshold=0.6, budget_rate=0.1)
        self.assertEqual(r["money"], 0.0)

    def test_cap_at_100_percent(self):
        days = [d("2026-10-23","workday",80,50,50,1.0)]
        r = monthly_summary(days, salary=10000, threshold=0.6, budget_rate=0.1)
        self.assertEqual(r["overall_rate"], 1.0)
        self.assertEqual(r["money"], 1000.0)

    def test_penalty_divides_money_by_three(self):
        days = [d("2026-10-23","workday",50,50,50,1.0,penalty=True)]
        r = monthly_summary(days, salary=9000, threshold=0.6, budget_rate=0.1)
        self.assertAlmostEqual(r["money"], 300.0)

class TestWeekly(unittest.TestCase):
    def test_week_totals(self):
        days = [d("2026-10-19","workday",20,40,40,0.5),
                d("2026-10-20","workday",30,40,40,0.75)]
        r = weekly_summary(days)
        self.assertEqual(r["earned_total"], 50.0)
        self.assertEqual(r["planned_total"], 80.0)

    def test_week_rate_is_average_of_daily_rates(self):
        """回归：以前把日的 60 分上限套在一周上，做一半也报 1.000。"""
        days = [d(f"2026-10-{19+i}", "workday", 15, 30, 30, 0.5) for i in range(7)]
        self.assertAlmostEqual(weekly_summary(days)["rate"], 0.5)

    def test_week_rate_reports_real_progress(self):
        days = [d(f"2026-10-{19+i}", "workday", 30, 30, 30, 1.0) for i in range(7)]
        self.assertAlmostEqual(weekly_summary(days)["rate"], 1.0)

    def test_partial_week_matches_monthly_for_the_same_days(self):
        days = [d("2026-10-23","workday",10.5,3,30,0.350),
                d("2026-10-25","weekend",11,17,30,0.367)]
        weekly = weekly_summary(days)["rate"]
        monthly = monthly_summary(days, salary=0, threshold=0.6, budget_rate=0.1)["overall_rate"]
        self.assertAlmostEqual(weekly, monthly)
        # 双休侧按组内合计重算（11/30），不直接用当天 frontmatter 的 0.367
        self.assertAlmostEqual(weekly, (0.350 + 11 / 30) / 2, places=6)

    def test_week_rate_does_not_treat_empty_side_as_zero(self):
        """只有工作日数据的一周：取工作日那一侧，不被空的周末拉低。"""
        days = [d("2026-10-19","workday",30,30,30,1.0),
                d("2026-10-20","workday",30,30,30,1.0)]
        self.assertAlmostEqual(weekly_summary(days)["rate"], 1.0)

    def test_week_summary_exposes_both_sides(self):
        days = [d("2026-10-23","workday",30,30,30,1.0),
                d("2026-10-24","weekend",15,30,30,0.5)]
        r = weekly_summary(days)
        self.assertAlmostEqual(r["weekday_rate"], 1.0)
        self.assertAlmostEqual(r["weekend_rate"], 0.5)
        self.assertAlmostEqual(r["rate"], 0.75)

class TestRender(unittest.TestCase):
    """审阅修复：frontmatter 是机器可读层，布尔必须 true/false；周报要带消费合计。"""

    def test_monthly_frontmatter_penalty_is_machine_readable(self):
        from lib.report import render_monthly
        for flag in (True, "true"):
            days = [d("2026-10-23","workday",50,50,50,1.0,penalty=flag)]
            text = render_monthly(days, month="2026-10", salary=9000,
                                  threshold=0.6, budget_rate=0.1)
            lines = text.splitlines()
            end = lines.index("---", 1)
            frontmatter = "\n".join(lines[1:end])
            body = "\n".join(lines[end + 1:])
            self.assertIn("penalty_applied: true", frontmatter)
            self.assertNotIn("是", frontmatter)
            self.assertIn("当月触发惩罚（金额扣 2/3）：是", body)

    def test_weekly_renders_consumption_totals(self):
        from datetime import date
        from lib.report import render_weekly
        days = [dict(d("2026-10-19","workday",20,40,40,0.5),
                     spent_daily=6, spent_weekly=0),
                dict(d("2026-10-24","weekend",20,20,20,1.0),
                     spent_daily=4, spent_weekly=10)]
        text = render_weekly(days, start=date(2026,10,19), end=date(2026,10,25))
        self.assertIn("消费：日账 10 分 / 周账 10 分", text)

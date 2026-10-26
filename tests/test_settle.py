import unittest, sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.config import Config
from lib.models import Task, Habit, FocusTask, FocusRecord, DayInputs
from lib.settle import settle_day

TZ8 = timezone(timedelta(hours=8))
D = date(2026, 10, 25)  # Sunday

def task(id, title, priority=3, due=None, done=None, repeat=None, tags=()):
    return Task(id=id, project_id="p", project_name="P", title=title, priority=priority,
                due_date=due, completed_time=done, repeat_flag=repeat, tags=tags)

def done_at(h, m=0):
    return datetime(2026, 10, 25, h, m, tzinfo=TZ8)

class TestSettle(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_denominator_floor_and_cap(self):
        tasks = (task("1", "小事 $1", due=done_at(9), done=done_at(9)),)
        s = settle_day(DayInputs(day=D, tasks=tasks, habits=(), habit_values={}, focus=()), self.cfg)
        self.assertEqual(s.planned_total, 1.0)
        self.assertEqual(s.denominator, 30.0)
        many = tuple(task(str(i), f"事{i} $10", due=done_at(9), done=done_at(9)) for i in range(10))
        s = settle_day(DayInputs(day=D, tasks=many, habits=(), habit_values={}, focus=()), self.cfg)
        self.assertEqual(s.denominator, 60.0)

    def test_earned_and_rate(self):
        tasks = (task("1", "写周报 $4", due=done_at(9), done=done_at(10)),)
        s = settle_day(DayInputs(day=D, tasks=tasks, habits=(), habit_values={}, focus=()), self.cfg)
        self.assertEqual(s.earned_task, 4.0)
        self.assertEqual(s.rate, 0.133)  # 4/30, rounded to 3 decimals

    def test_late_subjective_half_and_pending(self):
        due = done_at(9)
        t = task("1", "写周报 $4", due=due, done=done_at(12))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=(), habit_values={}, focus=()), self.cfg)
        self.assertEqual(s.earned_task, 4.0)
        self.assertTrue(s.late_pending)
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=(), habit_values={}, focus=(),
                                  late_subjective_ids=frozenset({"1"})), self.cfg)
        self.assertEqual(s.earned_task, 2.0)
        self.assertFalse(s.late_pending)

    def test_habit_ratio_and_dedupe(self):
        habits = (Habit(id="h1", name="面膜 $1", goal=1),)
        t = task("1", "面膜", due=done_at(9), done=done_at(9))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=habits, habit_values={"h1": 1}, focus=()), self.cfg)
        self.assertEqual(s.earned_task, 0.0)
        self.assertEqual(s.earned_habit, 1.0)

    def test_recurring_without_dollar_excluded(self):
        t = task("1", "十点睡", priority=5, repeat="RRULE:FREQ=DAILY", due=done_at(9), done=done_at(9))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=(), habit_values={}, focus=()), self.cfg)
        self.assertEqual(s.earned_task, 0.0)
        self.assertEqual(s.planned_total, 0.0)

    def test_weekday_consumption_daily_only(self):
        # 2026-10-26 is Monday; previous spendable 20 points => 40 minutes
        t = task("c1", "看剧", tags=("积分消费",), due=datetime(2026,10,26,20,0,tzinfo=TZ8),
                 done=datetime(2026,10,26,21,0,tzinfo=TZ8))
        f = FocusRecord(id="f1", type=0, start=datetime(2026,10,26,20,0,tzinfo=TZ8),
                        end=datetime(2026,10,26,20,30,tzinfo=TZ8),
                        tasks=(FocusTask("c1", datetime(2026,10,26,20,0,tzinfo=TZ8),
                                         datetime(2026,10,26,20,30,tzinfo=TZ8)),))
        s = settle_day(DayInputs(day=date(2026,10,26), tasks=(t,), habits=(), habit_values={},
                                  focus=(f,), previous_spendable=20), self.cfg)
        self.assertEqual(s.spent_daily, 15.0)   # 30 min / 2
        self.assertEqual(s.spent_weekly, 0.0)

    def test_weekend_consumption_daily_then_weekly(self):
        # 2026-10-25 Sunday; previous spendable 10 => 20 min, rest from weekly
        t = task("c1", "看剧", tags=("积分消费",), due=done_at(20), done=done_at(21))
        f = FocusRecord(id="f1", type=0, start=done_at(20), end=done_at(21),
                        tasks=(FocusTask("c1", done_at(20), done_at(21)),))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=(), habit_values={}, focus=(f,),
                                  previous_spendable=10, weekly_earned_before=100, weekly_spent_before=0), self.cfg)
        self.assertEqual(s.spent_daily, 10.0)   # 20 min / 2
        self.assertEqual(s.spent_weekly, 40.0)  # remaining 40 min / 1

    def test_consumption_without_focus_uses_dollar(self):
        t = task("c1", "看剧 $30", tags=("积分消费",), due=done_at(20), done=done_at(21))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=(), habit_values={}, focus=(),
                                  previous_spendable=20, weekly_earned_before=100), self.cfg)
        self.assertEqual(s.spent_daily, 20.0)      # 日账先扣 20 分
        self.assertEqual(s.spent_weekly, 10.0)     # 剩 10 分从周账扣
        self.assertEqual(s.unmet_points, 0.0)

    def test_penalty_divides_spendable(self):
        habits = (Habit(id="p1", name="惩罚习惯", goal=5),)
        t = task("1", "突破 $30", due=done_at(9), done=done_at(9))
        s = settle_day(DayInputs(day=D, tasks=(t,), habits=habits,
                                  habit_values={"p1": 1}, focus=()), self.cfg)
        self.assertTrue(s.penalty_applied)
        self.assertAlmostEqual(s.spendable, 25.0 / 3.0)
        self.assertAlmostEqual(s.weekly_balance, 10.0)  # 30 / 3
        self.assertFalse(s.weekly_penalty_pending)

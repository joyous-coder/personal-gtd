import unittest, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.models import Task
from lib.scoring import (parse_task_points, parse_habit_points, priority_base,
    round_half, habit_points, normalize_name, task_effective_points, task_final_points)

class TestParsing(unittest.TestCase):
    def test_task_points_trailing_only(self):
        self.assertEqual(parse_task_points("写周报 $4"), 4.0)
        self.assertEqual(parse_task_points("买 $5 牛奶 $3"), 3.0)
        self.assertIsNone(parse_task_points("无积分"))

    def test_habit_points_anywhere(self):
        self.assertEqual(parse_habit_points("@ 阅读 $3 22点半之前"), 3.0)
        self.assertEqual(parse_habit_points("学习$4 %60"), 4.0)
        self.assertIsNone(parse_habit_points("洗澡"))

    def test_priority_base(self):
        self.assertEqual(priority_base(5), 3.0)
        self.assertEqual(priority_base(3), 2.0)
        self.assertEqual(priority_base(1), 1.0)
        self.assertEqual(priority_base(0), 0.5)
        self.assertEqual(priority_base(2), 0.5)

    def test_round_half(self):
        self.assertEqual(round_half(0.25), 0.5)
        self.assertEqual(round_half(0.74), 0.5)
        self.assertEqual(round_half(0.75), 1.0)

class TestHabit(unittest.TestCase):
    def test_goal_ratio_and_cap(self):
        self.assertEqual(habit_points("运动 $1", 6, 3), 0.5)
        self.assertEqual(habit_points("运动 $1", 6, 6), 1.0)
        self.assertEqual(habit_points("运动 $1", 6, 9), 1.0)
        self.assertEqual(habit_points("运动 $1", 6, 0), 0.0)

    def test_no_dollar_is_zero(self):
        self.assertEqual(habit_points("洗澡", 1, 1), 0.0)

    def test_goal_one(self):
        self.assertEqual(habit_points("阅读 $3", 1, 1), 3.0)

class TestNames(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_name("@ 阅读 $3 22点半之前"), "阅读 22点半之前")
        self.assertEqual(normalize_name("学习$4 %60"), "学习")
        self.assertEqual(normalize_name("  面膜 "), "面膜")

class TestTaskPoints(unittest.TestCase):
    def test_explicit_wins(self):
        t = Task(id="1", project_id="p", project_name="P", title="写周报 $4", priority=5)
        self.assertEqual(task_effective_points(t), 4.0)

    def test_priority_fallback(self):
        t = Task(id="1", project_id="p", project_name="P", title="写周报", priority=3)
        self.assertEqual(task_effective_points(t), 2.0)

    def test_recurring_without_dollar_excluded(self):
        t = Task(id="1", project_id="p", project_name="P", title="十点睡",
                 priority=5, repeat_flag="RRULE:FREQ=DAILY")
        self.assertIsNone(task_effective_points(t))

    def test_parent_task_excluded(self):
        t = Task(id="1", project_id="p", project_name="P", title="父任务 $6",
                 priority=5, child_ids=("2",))
        self.assertIsNone(task_effective_points(t))

    def test_child_without_dollar_is_zero(self):
        t = Task(id="2", project_id="p", project_name="P", title="子任务",
                 priority=5, parent_id="1")
        self.assertEqual(task_effective_points(t), 0.0)

    def test_late_subjective_halves(self):
        due = datetime(2026, 10, 25, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        done = datetime(2026, 10, 25, 12, 0, tzinfo=timezone(timedelta(hours=8)))
        t = Task(id="1", project_id="p", project_name="P", title="写周报 $4",
                 priority=5, due_date=due, completed_time=done)
        self.assertEqual(task_final_points(t, late_subjective=True, breakthrough=False), (2.0, True))

    def test_breakthrough_not_halved(self):
        due = datetime(2026, 10, 25, 10, 0, tzinfo=timezone(timedelta(hours=8)))
        done = datetime(2026, 10, 25, 12, 0, tzinfo=timezone(timedelta(hours=8)))
        t = Task(id="1", project_id="p", project_name="P", title="上线 $6",
                 priority=5, due_date=due, completed_time=done, tags=("突破",))
        self.assertEqual(task_final_points(t, late_subjective=True, breakthrough=True), (6.0, True))

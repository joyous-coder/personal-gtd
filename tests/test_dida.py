import json, tempfile, unittest, sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.dida import DEFAULT_INBOX_ID, DidaClient, load_dida_token, parse_dt

FIX = Path(__file__).parent / "fixtures"
TZ8 = timezone(timedelta(hours=8))

class TestParse(unittest.TestCase):
    def test_parse_dt_utc(self):
        dt = parse_dt("2026-10-25T03:18:40.000+0000")
        self.assertEqual(dt.astimezone(TZ8).strftime("%Y-%m-%d %H:%M"), "2026-10-25 11:18")

    def test_load_token(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"access_token": "abc"}), encoding="utf-8")
            self.assertEqual(load_dida_token(p), "abc")

class TestClient(unittest.TestCase):
    def setUp(self):
        self.c = DidaClient("tok")

    def test_habit_checkins_uses_habitIds(self):
        fixture = json.loads((FIX / "dida_habit_checkins.json").read_text(encoding="utf-8"))
        with patch.object(self.c, "_request", return_value=fixture) as m:
            values = self.c.habit_checkins(["h1", "h2"], date(2026, 10, 19), date(2026, 10, 25))
            self.assertEqual(values[("h1", date(2026, 10, 21))], 0.0)
            self.assertEqual(values[("h1", date(2026, 10, 20))], 1.0)
            args, kwargs = m.call_args
            self.assertEqual(kwargs["query"]["habitIds"], "h1,h2")
            self.assertNotIn("habits", kwargs["query"])
            self.assertEqual(kwargs["query"]["from"], "20261019")
            # `to` 是排他的：闭区间 10-19 ~ 10-25 要传 20261026
            self.assertEqual(kwargs["query"]["to"], "20261026")

    def test_habit_checkins_single_day_sends_next_day_as_exclusive_to(self):
        """实测：from=to=当天 返回空；必须 to=次日，否则当天打卡全部丢失。"""
        with patch.object(self.c, "_request", return_value=[]) as m:
            self.c.habit_checkins(["h1"], date(2026, 10, 25), date(2026, 10, 25))
        query = m.call_args.kwargs["query"]
        self.assertEqual(query["from"], "20261025")
        self.assertEqual(query["to"], "20261026")

    def test_completed_does_not_send_projectIds(self):
        fixture = json.loads((FIX / "dida_completed.json").read_text(encoding="utf-8"))
        with patch.object(self.c, "_request", return_value=fixture) as m:
            tasks = self.c.completed_tasks(date(2026, 10, 24), date(2026, 10, 25))
            self.assertEqual(len(tasks), 2)
            body = m.call_args.kwargs["body"]
            self.assertNotIn("projectIds", body)
            self.assertIn("startDate", body)

    def test_focus_parses_task_ids_and_minutes(self):
        fixture = json.loads((FIX / "dida_focus.json").read_text(encoding="utf-8"))
        with patch.object(self.c, "_request", return_value=fixture):
            records = self.c.focus(date(2026, 10, 25), date(2026, 10, 25), 0)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].tasks[0].task_id, "t1")
            self.assertAlmostEqual(records[0].minutes_for("t1"), 25.0)

    def test_inbox_project_data(self):
        fixture = json.loads((FIX / "dida_project_data.json").read_text(encoding="utf-8"))
        with patch.object(self.c, "_request", return_value=fixture):
            tasks = self.c.project_tasks("inbox", "收集箱")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].project_name, "收集箱")

    def test_habits_parses_name_and_goal(self):
        fixture = json.loads((FIX / "dida_habits.json").read_text(encoding="utf-8"))
        with patch.object(self.c, "_request", return_value=fixture):
            habits = self.c.habits()
            self.assertEqual(habits[0].goal, 1.0)
            self.assertEqual(habits[1].name, "运动 $1")


class TestInboxIdIsNotHardcoded(unittest.TestCase):
    """收集箱 ID 里带滴答账号号，不能写死在代码里（会跟着仓库发出去）。"""

    def test_default_inbox_id_is_empty(self):
        self.assertEqual(DEFAULT_INBOX_ID, "")

    def test_all_open_tasks_does_not_request_with_empty_id(self):
        client = DidaClient("tok", inbox_id="")
        with patch.object(client, "_request", return_value=[]) as m:
            tasks = client.all_open_tasks()
        self.assertEqual(tasks, [])
        for call in m.call_args_list:
            self.assertNotIn("", call.args)

    def test_all_open_tasks_fetches_the_configured_inbox(self):
        client = DidaClient("tok", inbox_id="inbox1")

        def fake(method, path, **kwargs):
            if path == "/project":
                return [{"id": "p1", "name": "清单A"}]
            if path == "/project/inbox1/data":
                return {"tasks": [{"id": "t1", "title": "x"}]}
            return {"tasks": []}

        with patch.object(client, "_request", side_effect=fake):
            tasks = client.all_open_tasks()
        self.assertTrue(any(task.project_name == "收集箱" for task in tasks))

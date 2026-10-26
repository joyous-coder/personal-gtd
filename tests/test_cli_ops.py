# tests/test_cli_ops.py
import os, tempfile, unittest, sys
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gtd
from lib.config import Config
from lib.notes import FolderWriter

class TestOps(unittest.TestCase):
    def test_balance_reads_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            w = FolderWriter(Path(d))
            w.write("7-规划回顾/2-回顾/1-日维度/review-2026-10-25-星期日.md",
                    "---\ndate: 2026-10-25\nearned_total: 11\nspendable: 22\nweekly_balance: 27\n---\n")
            with patch.object(gtd, "writer_chain", return_value=[w]), patch("sys.stdout") as out:
                code = gtd.main(["balance", "--date", "2026-10-25", "--vault-dir", d])
            self.assertEqual(code, 0)

    def test_backfill_is_idempotent(self):
        calls = []
        def fake(day, dry, **_kwargs):
            calls.append((day, dry))
            return 0
        with (
            tempfile.TemporaryDirectory() as d,
            patch.object(gtd, "_settle_one", side_effect=fake),
            patch("sys.stdout"),
        ):
            gtd.main(["backfill", "--from", "2026-10-24", "--to", "2026-10-25",
                      "--dry-run", "--vault-dir", d])
        self.assertEqual([c[0] for c in calls], ["2026-10-24", "2026-10-25"])

    def test_audit_reports_mismatch(self):
        from datetime import date
        from lib.models import DayScore
        fake_score = DayScore(day=date(2026,10,25), kind="weekend", earned_task=1,
            earned_habit=0, earned_total=1, planned_total=30, denominator=30, rate=0.033,
            late_discount=0, late_pending=False, reserve=5, spendable=0, spent_daily=0,
            spent_weekly=0, unmet_minutes=0, unmet_points=0, daily_balance=0,
            weekly_earned=1, weekly_spent=0, weekly_balance=1, weekly_penalty_pending=False,
            penalty_applied=False, items=())
        with tempfile.TemporaryDirectory() as d:
            w = FolderWriter(Path(d))
            w.write("7-规划回顾/2-回顾/1-日维度/review-2026-10-25-星期日.md",
                    "---\ndate: 2026-10-25\nearned_total: 999\n---\n")
            with patch.object(gtd, "writer_chain", return_value=[w]), \
                 patch.object(gtd, "compute_day_score", return_value=fake_score), \
                 patch("sys.stdout"):
                code = gtd.main(["audit", "--date", "2026-10-25", "--vault-dir", d])
            self.assertEqual(code, 1)

class TestLegacyNotesAreNotLedgers(unittest.TestCase):
    """审阅修复：`1-日维度` 里的老自适应日总结没有 frontmatter，不能算 0% 的一天。"""

    LEDGER_DAY = date(2026, 10, 22)   # 星期四，本 skill 写的账本
    LEGACY_DAY = date(2026, 10, 23)   # 星期五，老的自适应日总结（无 frontmatter）

    def _vault(self, vault):
        w = FolderWriter(Path(vault))
        w.write(
            gtd._review_rel_path(self.LEDGER_DAY, Config()),
            "---\ndate: 2026-10-22\nkind: workday\nearned_task: 30\nearned_habit: 0\n"
            "earned_total: 30\nplanned_total: 30\ndenominator: 30\nrate: 1.000\n"
            "spendable: 25\nweekly_earned: 30\nweekly_spent: 0\nweekly_balance: 30\n"
            "penalty_applied: false\n---\n\n# 日回顾\n",
        )
        w.write(
            gtd._review_rel_path(self.LEGACY_DAY, Config()),
            "# 2026-10-23 星期五 日总结\n\n---\n\n## 【时间管理】\n\n- 老格式，没有 frontmatter\n",
        )
        return w

    def _run(self, vault, argv, config=None):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(gtd, "writer_chain", return_value=[FolderWriter(Path(vault))]),
            patch.object(gtd, "load_config", return_value=config or Config()),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = gtd.main([*argv, "--vault-dir", vault])
        return code, out.getvalue(), err.getvalue()

    def test_report_does_not_count_legacy_note_as_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault(d)
            code, out, err = self._run(
                d, ["report", "--from", "2026-10-22", "--to", "2026-10-23"]
            )
        self.assertEqual(code, 0, err)
        self.assertIn("有日回顾 1 天", out)
        self.assertIn("| 2026-10-22 |", out)
        self.assertNotIn("| 2026-10-23 |", out)          # 老笔记不进日明细
        self.assertIn("完成率：1.000", out)               # 只按账本那天算，不拉成 0.5
        self.assertIn("不是账本笔记，已跳过", err)

    def test_monthly_does_not_count_legacy_note_as_zero(self):
        config = Config(salary=9000)
        with tempfile.TemporaryDirectory() as d:
            self._vault(d)
            code, out, err = self._run(d, ["monthly", "--month", "2026-10"], config)
        self.assertEqual(code, 0, err)
        self.assertIn("有日回顾 1 天", out)
        self.assertIn("工作日完成率：1.000", out)
        # 若把老笔记当 0% 工作日，avg(1, 0) = 0.5 < 0.6 → 金额 0
        self.assertIn("本月金额：900.00", out)

    def test_balance_reports_legacy_note_as_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault(d)
            code, out, err = self._run(d, ["balance", "--date", "2026-10-23"])
        self.assertEqual(code, 1)
        self.assertIn("不是账本笔记，已跳过", err)
        self.assertNotIn("spendable", out)

    def test_balance_still_works_on_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault(d)
            code, out, err = self._run(d, ["balance", "--date", "2026-10-22"])
        self.assertEqual(code, 0, err)
        self.assertIn("spendable: 25", out)


class TestInitDirs(unittest.TestCase):
    """Task 10 裁定：init 在 folder 模式下补齐 721/722/723 三个回顾目录，且幂等。"""

    def test_init_reports_not_writable_without_backend(self):
        """审阅修复：没有后端时 init 必须说清「现在还不能写入」并给出设置命令。"""
        import io
        from contextlib import redirect_stdout
        env = {
            "PERSONAL_GTD_VAULT_DIR": "",
            "PERSONAL_GTD_FNS_URL": "",
            "PERSONAL_GTD_FNS_TOKEN": "",
        }
        out = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(os.environ, env),
            patch.object(gtd, "init_config", return_value=Config()),
            redirect_stdout(out),
        ):
            self.assertEqual(gtd.main(["init"]), 0)
        text = out.getvalue()
        self.assertIn("writer：未配置", text)
        self.assertIn("现在还不能写入", text)
        self.assertIn("PERSONAL_GTD_VAULT_DIR", text)
        self.assertNotIn("D:\\Documents\\Obsidian_Vault", text)

    def test_init_creates_review_dirs_in_folder_mode(self):
        env = {
            "PERSONAL_GTD_VAULT_DIR": "",
            "PERSONAL_GTD_FNS_URL": "",
            "PERSONAL_GTD_FNS_TOKEN": "",
        }
        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(os.environ, env),
            patch.object(gtd, "init_config", return_value=Config()),
            patch("sys.stdout"),
        ):
            os.environ["PERSONAL_GTD_VAULT_DIR"] = d
            self.assertEqual(gtd.main(["init"]), 0)
            base = Path(d) / "7-规划回顾"
            self.assertTrue((base / "1-规划").is_dir(), "1-规划")
            self.assertTrue((base / "2-回顾").is_dir(), "2-回顾")
            for name in ("1-日维度", "2-周维度", "3-月维度"):
                self.assertTrue((base / "2-回顾" / name).is_dir(), name)
            # 重跑：目录已存在也不报错
            self.assertEqual(gtd.main(["init"]), 0)

class TestBackfillSkip(unittest.TestCase):
    """Task 10 复审：backfill 默认只补缺失日期，--force 才覆盖人写的日回顾。"""

    def _run(self, vault, *extra):
        calls = []

        def fake(day, dry, **_kwargs):
            calls.append(str(day))
            text = "---\ndate: %s\n---\n\n## 总结\n\n生成的\n" % day
            FolderWriter(Path(vault)).write(
                gtd._review_rel_path(gtd._coerce_day(day), Config()), text
            )
            return 0

        with patch.object(gtd, "_settle_one", side_effect=fake), patch("sys.stdout"):
            code = gtd.main(["backfill", "--from", "2026-10-24", "--to", "2026-10-25",
                             "--vault-dir", vault, *extra])
        return code, calls

    def test_existing_note_is_skipped_and_force_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            rel = gtd._review_rel_path(date(2026, 10, 24), Config())
            FolderWriter(Path(d)).write(
                rel, "---\ndate: 2026-10-24\n---\n\n人手写的总结\n"
            )
            note = Path(d) / rel

            # 默认：已存在的 10-24 跳过，只结算 10-25
            code, calls = self._run(d)
            self.assertEqual(code, 0)
            self.assertEqual(calls, ["2026-10-25"])
            self.assertIn("人手写的总结", note.read_text(encoding="utf-8"))

            # --force：两天都重算，旧内容被替换
            code, calls = self._run(d, "--force")
            self.assertEqual(code, 0)
            self.assertEqual(calls, ["2026-10-24", "2026-10-25"])
            self.assertNotIn("人手写的总结", note.read_text(encoding="utf-8"))
            self.assertIn("生成的", note.read_text(encoding="utf-8"))

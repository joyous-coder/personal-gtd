# tests/test_cli_install.py
"""`gtd selfcheck` / `gtd pack`，以及"源码缺失就拒绝启动"的预检。"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gtd  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def make_lib(root: Path, missing=()) -> Path:
    lib = root / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in gtd.REQUIRED_MODULES:
        if name in missing:
            continue
        (lib / f"{name}.py").write_text("# module\n", encoding="utf-8")
    cache = lib / "__pycache__"
    cache.mkdir(exist_ok=True)
    for name in missing:
        (cache / f"{name}.cpython-312.pyc").write_bytes(b"\x00")
    return lib


class TestSelfcheckCommand(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gtd.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_real_tree_is_healthy(self):
        code, out, _ = self._run(["selfcheck"])
        self.assertEqual(code, 0)
        self.assertIn("源码模块", out)

    def test_missing_source_fails(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d), missing=("scoring",))
            code, out, _ = self._run(["selfcheck", "--lib-dir", str(lib)])
            self.assertEqual(code, 1)
            self.assertIn("scoring", out)

    def test_json_output_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d), missing=("report",))
            code, out, _ = self._run(["selfcheck", "--lib-dir", str(lib), "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(out)
            self.assertFalse(payload["ok"])
            self.assertIn("report", payload["missing_sources"])


class TestPackCommand(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gtd.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_pack_writes_source_only_zip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "skill"
            (root / "scripts" / "lib").mkdir(parents=True)
            (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            (root / "scripts" / "lib" / "scoring.py").write_text("# s\n", encoding="utf-8")
            (root / "scripts" / "lib" / "__pycache__").mkdir()
            (root / "scripts" / "lib" / "__pycache__" / "scoring.cpython-312.pyc").write_bytes(b"x")
            out_zip = Path(d) / "personal-gtd.zip"
            code, _, _ = self._run(
                ["pack", "--root", str(root), "--out", str(out_zip)]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out_zip.is_file())
            with zipfile.ZipFile(out_zip) as zf:
                names = zf.namelist()
            self.assertIn("personal-gtd/scripts/lib/scoring.py", names)
            self.assertFalse([n for n in names if n.endswith(".pyc")])

    def test_pack_list_does_not_write_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "skill"
            root.mkdir()
            (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
            out_zip = Path(d) / "personal-gtd.zip"
            code, out, _ = self._run(
                ["pack", "--root", str(root), "--out", str(out_zip), "--list"]
            )
            self.assertEqual(code, 0)
            self.assertIn("SKILL.md", out)
            self.assertFalse(out_zip.exists())


class TestPreflight(unittest.TestCase):
    """源码缺失时，gtd.py 要在 import 崩掉之前就给出人话。"""

    def test_missing_module_source_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "scripts"
            shutil.copytree(SCRIPTS, tree)
            (tree / "lib" / "scoring.py").unlink()
            proc = subprocess.run(
                [sys.executable, str(tree / "gtd.py"), "score", "--title", "x"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("scoring", proc.stderr)
            self.assertIn("源码", proc.stderr)


class TestLauncherGuards(unittest.TestCase):
    """启动器也要挡住"只同步到 .pyc"的残安装。"""

    LAUNCHERS = ("gtd", "gtd.cmd")

    def _modules_in(self, path: Path) -> list[str]:
        import re

        text = path.read_text(encoding="utf-8")
        found = re.search(r"for\s+(?:%%)?m\s+in\s+\(?([^)\n;]+)\)?", text)
        self.assertIsNotNone(found, f"{path.name} 里找不到模块清单")
        return found.group(1).split()

    def test_launcher_module_list_matches_required_modules(self):
        from lib.health import REQUIRED_MODULES

        for name in self.LAUNCHERS:
            with self.subTest(launcher=name):
                self.assertEqual(
                    sorted(self._modules_in(SCRIPTS / name)),
                    sorted(REQUIRED_MODULES),
                )

    def test_launchers_refuse_a_pyc_only_install(self):
        for name in self.LAUNCHERS:
            with self.subTest(launcher=name):
                text = (SCRIPTS / name).read_text(encoding="utf-8")
                self.assertIn("lib", text)
                self.assertIn("2", text)  # 缺源码时的退出码


if __name__ == "__main__":
    unittest.main()

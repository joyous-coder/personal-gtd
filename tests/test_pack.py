# tests/test_pack.py
"""打包：跨机器安装用的源码包（不含字节码）。"""
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.pack import build_pack, collect_files  # noqa: E402


def make_skill(root: Path) -> Path:
    (root / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "scripts" / "lib" / "scoring.py").write_text("# scoring\n", encoding="utf-8")
    (root / "scripts" / "lib" / "__pycache__").mkdir(parents=True)
    (root / "scripts" / "lib" / "__pycache__" / "scoring.cpython-312.pyc").write_bytes(b"\x00")
    (root / "tests").mkdir()
    (root / "tests" / "test_scoring.py").write_text("# test\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    return root


class TestCollectFiles(unittest.TestCase):
    def test_excludes_pycache_and_pyc(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            kept, skipped = collect_files(root)
            self.assertIn("scripts/lib/scoring.py", kept)
            self.assertNotIn("scripts/lib/__pycache__/scoring.cpython-312.pyc", kept)
            self.assertTrue(any("scoring.cpython-312.pyc" in s for s in skipped))

    def test_excludes_git_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            kept, _ = collect_files(root)
            self.assertNotIn(".git/config", kept)

    def test_paths_use_posix_separators(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            kept, _ = collect_files(root)
            self.assertTrue(all("\\" not in p for p in kept))


class TestBuildPack(unittest.TestCase):
    def test_zip_contains_sources_under_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            out = Path(d) / "personal-gtd.zip"
            result = build_pack(root, out, name="personal-gtd")
            self.assertTrue(out.is_file())
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            self.assertIn("personal-gtd/SKILL.md", names)
            self.assertIn("personal-gtd/scripts/lib/scoring.py", names)
            self.assertEqual(result.archive, str(out))

    def test_zip_has_no_bytecode(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            out = Path(d) / "personal-gtd.zip"
            build_pack(root, out, name="personal-gtd")
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
            self.assertFalse([n for n in names if n.endswith(".pyc")])
            self.assertFalse([n for n in names if "__pycache__" in n])

    def test_result_reports_included_and_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_skill(Path(d))
            out = Path(d) / "personal-gtd.zip"
            result = build_pack(root, out, name="personal-gtd")
            self.assertIn("SKILL.md", result.files)
            self.assertTrue(any(".pyc" in s for s in result.skipped))


if __name__ == "__main__":
    unittest.main()

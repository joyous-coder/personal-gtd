# tests/test_health.py
"""安装自检：源码齐全、字节码污染、写入后端、滴答依赖。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib.health import (  # noqa: E402
    REQUIRED_MODULES,
    build_report,
    check_install,
    find_stray_bytecode,
    render_report,
    scan_modules,
)


def make_lib(root: Path, modules=REQUIRED_MODULES, bytecode=()) -> Path:
    lib = root / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in modules:
        (lib / f"{name}.py").write_text("# module\n", encoding="utf-8")
    for rel in bytecode:
        target = lib / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00")
    return lib


class TestScanModules(unittest.TestCase):
    def test_source_only_module_is_healthy(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d), modules=("config",))
            states = {s.name: s for s in scan_modules(lib)}
            self.assertTrue(states["config"].has_source)
            self.assertFalse(states["config"].has_bytecode)

    def test_pyc_only_module_has_no_source(self):
        """另一台机器上真实发生过：模块只剩 .pyc，源码没同步过来。"""
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                modules=("config",),
                bytecode=("__pycache__/scoring.cpython-312.pyc",),
            )
            states = {s.name: s for s in scan_modules(lib)}
            self.assertFalse(states["scoring"].has_source)
            self.assertTrue(states["scoring"].has_bytecode)

    def test_module_with_both_source_and_bytecode_counts_as_source(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                modules=("config",),
                bytecode=("__pycache__/config.cpython-312.pyc",),
            )
            states = {s.name: s for s in scan_modules(lib)}
            self.assertTrue(states["config"].has_source)
            self.assertTrue(states["config"].has_bytecode)


class TestCheckInstall(unittest.TestCase):
    def test_missing_source_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                modules=tuple(m for m in REQUIRED_MODULES if m != "scoring"),
                bytecode=("__pycache__/scoring.cpython-312.pyc",),
            )
            missing, _ = check_install(lib)
            self.assertEqual(missing, ["scoring"])

    def test_clean_tree_reports_nothing_missing(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            missing, _ = check_install(lib)
            self.assertEqual(missing, [])

    def test_stray_bytecode_paths_are_relative_to_lib(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                bytecode=("__pycache__/scoring.cpython-312.pyc",),
            )
            stray = find_stray_bytecode(lib)
            self.assertEqual(stray, ["__pycache__/scoring.cpython-312.pyc"])


class TestBuildReport(unittest.TestCase):
    def _report(self, lib, env=None, which=None, token_file=None):
        return build_report(
            lib,
            env=env if env is not None else {},
            which=which if which is not None else (lambda _name: None),
            dida_token_path=token_file,
        )

    def test_missing_source_makes_report_not_ok(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                modules=tuple(m for m in REQUIRED_MODULES if m != "report"),
                bytecode=("__pycache__/report.cpython-312.pyc",),
            )
            report = self._report(lib)
            self.assertFalse(report.ok)
            self.assertIn("report", report.missing_sources)

    def test_clean_tree_report_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            self.assertTrue(self._report(lib).ok)

    def test_fns_env_selects_fns_writer(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            env = {
                "PERSONAL_GTD_FNS_URL": "https://example.invalid",
                "PERSONAL_GTD_FNS_TOKEN": "t",
            }
            self.assertEqual(self._report(lib, env=env).writer, "fns")

    def test_vault_dir_env_selects_folder_writer(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            env = {"PERSONAL_GTD_VAULT_DIR": str(Path(d))}
            self.assertEqual(self._report(lib, env=env).writer, "folder")

    def test_no_writer_is_a_warning_not_a_problem(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            report = self._report(lib)
            self.assertEqual(report.writer, "none")
            self.assertTrue(report.ok)
            self.assertTrue(report.warnings)

    def test_missing_dida_is_a_warning_not_a_problem(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            report = self._report(lib)
            self.assertFalse(report.dida_installed)
            self.assertTrue(report.ok)

    def test_dida_token_file_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(Path(d))
            token = Path(d) / "dida.json"
            token.write_text('{"access_token": "x"}', encoding="utf-8")
            report = self._report(lib, which=lambda _n: "/usr/bin/dida", token_file=token)
            self.assertTrue(report.dida_installed)
            self.assertTrue(report.dida_token_found)


class TestRenderReport(unittest.TestCase):
    def test_report_names_the_missing_module(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                modules=tuple(m for m in REQUIRED_MODULES if m != "scoring"),
                bytecode=("__pycache__/scoring.cpython-312.pyc",),
            )
            text = render_report(
                build_report(
                    lib,
                    env={},
                    which=lambda _n: None,
                    dida_token_path=None,
                )
            )
            self.assertIn("scoring", text)
            self.assertIn("源码", text)

    def test_report_mentions_stray_bytecode(self):
        with tempfile.TemporaryDirectory() as d:
            lib = make_lib(
                Path(d),
                bytecode=("__pycache__/scoring.cpython-312.pyc",),
            )
            text = render_report(
                build_report(
                    lib,
                    env={},
                    which=lambda _n: None,
                    dida_token_path=None,
                )
            )
            self.assertIn(".pyc", text)


class TestEnvNamesMatchNotes(unittest.TestCase):
    """health 不 import lib.notes（预检要轻），但环境变量名不能漂。"""

    def test_env_names_are_the_same(self):
        from lib import notes
        from lib import health

        self.assertEqual(health.ENV_FNS_URL, notes.ENV_FNS_URL)
        self.assertEqual(health.ENV_FNS_TOKEN, notes.ENV_FNS_TOKEN)
        self.assertEqual(health.ENV_VAULT_DIR, notes.ENV_VAULT_DIR)


if __name__ == "__main__":
    unittest.main()

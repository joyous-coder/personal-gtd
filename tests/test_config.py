import json, os, tempfile, unittest, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.config import Config, load_config, init_config, DEFAULT_CONFIG_PATH, DEFAULT_DIDA_TOKEN_PATH

class TestConfig(unittest.TestCase):
    def test_default_paths_are_home_based(self):
        home = str(Path.home())
        self.assertTrue(DEFAULT_CONFIG_PATH.startswith(home))
        self.assertTrue(DEFAULT_DIDA_TOKEN_PATH.startswith(home))

    def test_env_overrides_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            p.write_text(json.dumps({"reserve": 7}), encoding="utf-8")
            with patch.dict(os.environ, {"PERSONAL_GTD_CONFIG": str(p)}):
                cfg = load_config()
            self.assertEqual(cfg.reserve, 7.0)
            self.assertEqual(cfg.config_path, str(p))

    def test_env_overrides_dida_token_path(self):
        with tempfile.TemporaryDirectory() as d:
            token = Path(d) / "dida.json"
            with patch.dict(os.environ, {"PERSONAL_GTD_DIDA_CONFIG": str(token)}):
                cfg = load_config(Path(d) / "missing.json")
            self.assertEqual(cfg.dida_token_path, str(token))

    def test_config_path_reflects_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text("{}", encoding="utf-8")
            self.assertEqual(load_config(p).config_path, str(p))

    def test_day_rate_must_be_positive(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"day_rate": 0}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(p)

    def test_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = load_config(Path(d) / "missing.json")
            self.assertEqual(cfg.vault, "Obsidian_Vault")
            self.assertEqual(cfg.reserve, 5.0)
            self.assertEqual(cfg.tags["consumption"], "积分消费")

    def test_json_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"reserve": 8, "salary": 14000, "tags": {"consumption": "消费"}}), encoding="utf-8")
            cfg = load_config(p)
            self.assertEqual(cfg.reserve, 8.0)
            self.assertEqual(cfg.salary, 14000.0)
            self.assertEqual(cfg.tags["consumption"], "消费")
            self.assertEqual(cfg.tags["breakthrough"], "突破")

    def test_reserve_out_of_bounds_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"reserve": 11}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(p)

    def test_init_config_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "config.json"
            cfg = init_config(p)
            self.assertTrue(p.exists())
            self.assertEqual(cfg.reserve, 5.0)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["vault"], "Obsidian_Vault")

class TestInboxId(unittest.TestCase):
    """收集箱 ID 里带滴答账号号：放 config 里，不进代码库。"""

    def test_default_is_empty(self):
        self.assertEqual(Config().inbox_id, "")

    def test_can_be_configured(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"inbox_id": "inbox123"}), encoding="utf-8")
            self.assertEqual(load_config(p).inbox_id, "inbox123")


class TestGtdDirEnvOverride(unittest.TestCase):
    """只留一个目录变量：GTD 输出的根目录，skill 在它下面自己建子目录。"""

    def _load(self, extra_env, config_data=None):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps(config_data or {}), encoding="utf-8")
            with patch.dict(os.environ, extra_env):
                return load_config(p)

    def test_env_overrides_file(self):
        cfg = self._load(
            {"PERSONAL_GTD_DIR": "从这里写"},
            {"gtd_dir": "从文件写"},
        )
        self.assertEqual(cfg.gtd_dir, "从这里写")

    def test_file_value_is_used_when_env_is_absent(self):
        cfg = self._load({}, {"gtd_dir": "从文件写"})
        self.assertEqual(cfg.gtd_dir, "从文件写")

    def test_default_root(self):
        self.assertEqual(Config().gtd_dir, "7-规划回顾")

    def test_theory_dir_is_a_config_field(self):
        """理论目录是"读"的位置（用户已有的笔记），只走配置文件。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"theory_dir": "方法论/从这里读"}), encoding="utf-8")
            self.assertEqual(load_config(p).theory_dir, "方法论/从这里读")

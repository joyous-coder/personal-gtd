# tests/test_adapters.py
"""两个 adapter 的入口要对齐：同一批入口、同一个总入口、同一套收尾提示。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / "adapters" / "claude-code" / "commands"
BUNDLES = ROOT / "adapters" / "hermes" / "bundles"


def command_names() -> set[str]:
    return {path.stem for path in COMMANDS.glob("*.md")}


def bundle_names() -> set[str]:
    return {path.stem for path in BUNDLES.glob("*.yaml")}


class TestAdapterParity(unittest.TestCase):
    def test_commands_and_bundles_have_the_same_entries(self):
        self.assertEqual(command_names(), bundle_names())

    def test_total_entry_exists_on_both_sides(self):
        self.assertIn("gtd", command_names())
        self.assertIn("gtd", bundle_names())

    def test_every_bundle_loads_the_skill(self):
        for path in sorted(BUNDLES.glob("*.yaml")):
            with self.subTest(bundle=path.name):
                self.assertIn("personal-gtd", path.read_text(encoding="utf-8"))


class TestTotalEntry(unittest.TestCase):
    def test_total_entry_points_at_the_routing_table(self):
        for path in (COMMANDS / "gtd.md", BUNDLES / "gtd.yaml"):
            with self.subTest(entry=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("模式分流", text)
                self.assertIn("下一阶段", text)

    def test_every_entry_prompts_the_next_stage(self):
        for path in sorted(COMMANDS.glob("*.md")):
            with self.subTest(entry=path.name):
                self.assertIn("下一阶段", path.read_text(encoding="utf-8"))
        for path in sorted(BUNDLES.glob("*.yaml")):
            with self.subTest(entry=path.name):
                self.assertIn("下一阶段", path.read_text(encoding="utf-8"))


class TestCoreRule(unittest.TestCase):
    def test_skill_md_requires_the_next_stage_prompt(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("下一阶段", text)
        self.assertIn("只提示", text)


if __name__ == "__main__":
    unittest.main()

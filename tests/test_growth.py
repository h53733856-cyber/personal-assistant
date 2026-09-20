"""
agent.growth 成长机制的单元测试。
"""

import unittest
from unittest import mock

import config
import agent.growth as growth

from tests.helpers import TempDataDir


class TestGrowth(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_no_rules_returns_prompt_unchanged(self):
        self.assertEqual(growth.inject_rules("原始 prompt"), "原始 prompt")

    def test_record_feedback_and_inject(self):
        growth.record_feedback("报修时间格式统一为 yyyy-MM-dd HH:mm")

        rules = growth.list_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["name"], "feedback.md")

        prompt = growth.inject_rules("帮我分析这个任务")

        self.assertIn("规则文件：feedback.md", prompt)
        self.assertIn("yyyy-MM-dd HH:mm", prompt)
        self.assertTrue(prompt.endswith("帮我分析这个任务"))

    def test_readme_is_not_injected(self):
        readme = config.RULES_DIR / "README.md"
        readme.write_text("# 说明文档", encoding="utf-8")
        growth.record_feedback("一条反馈")

        rules = growth.list_rules()

        self.assertEqual([r["name"] for r in rules], ["feedback.md"])

    def test_record_feedback_with_git(self):
        with mock.patch("agent.growth._git_commit_rules") as fake:
            growth.record_feedback("反馈", commit=True)

        fake.assert_called_once()


if __name__ == "__main__":
    unittest.main()

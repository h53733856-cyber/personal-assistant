"""
agent.llm.ask_llm_json 的单元测试。

全部使用 mock，不调用真实 API。
"""

import unittest
from unittest import mock

from agent.llm import ask_llm_json, _extract_json_block


class TestExtractJsonBlock(unittest.TestCase):

    def test_plain_json(self):
        text = '{"a": 1}'
        self.assertEqual(_extract_json_block(text), '{"a": 1}')

    def test_markdown_fence(self):
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(_extract_json_block(text), '{"a": 1}')

    def test_extra_text_around(self):
        text = '好的，结果如下：\n{"a": 1}\n希望有帮助。'
        self.assertEqual(_extract_json_block(text), '{"a": 1}')

    def test_no_json(self):
        self.assertIsNone(_extract_json_block('没有 JSON'))


class TestAskLlmJson(unittest.TestCase):

    def test_clean_json(self):
        with mock.patch("agent.llm.ask_llm", return_value='{"ok": true}'):
            result = ask_llm_json("测试")
        self.assertEqual(result, {"ok": True})

    def test_markdown_fence(self):
        reply = '```json\n{"ok": true}\n```'
        with mock.patch("agent.llm.ask_llm", return_value=reply):
            result = ask_llm_json("测试")
        self.assertEqual(result, {"ok": True})

    def test_retry_after_bad_json(self):
        """第一次返回非法 JSON，重试后成功。"""
        replies = ['这不是 JSON', '{"ok": true}']

        with mock.patch("agent.llm.ask_llm", side_effect=replies) as fake_llm:
            result = ask_llm_json("测试")

        self.assertEqual(result, {"ok": True})
        # 第二次调用时 prompt 应该带上了错误反馈
        self.assertEqual(fake_llm.call_count, 2)
        self.assertIn("无法解析为 JSON", fake_llm.call_args_list[1].args[0])

    def test_all_retries_fail(self):
        with mock.patch(
            "agent.llm.ask_llm",
            side_effect=["bad", "still bad", "worse"],
        ):
            with self.assertRaises(ValueError):
                ask_llm_json("测试")


if __name__ == "__main__":
    unittest.main()

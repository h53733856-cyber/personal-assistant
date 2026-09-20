"""
entrypoints.cli 的行为测试（LLM 全部 mock）。
"""

import unittest
from unittest import mock

import agent.task_manager as tm
import agent.task_processor as tp
import entrypoints.cli as cli

from tests.helpers import TempDataDir

ANALYSIS = {
    "type": "宿舍报修",
    "core": "宿舍水龙头坏了，需要报修",
    "time": None,
    "deadline": None,
    "need_action": True,
    "action": "在 EHALL 提交宿舍报修申请",
}


class TestCli(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_interact_quits_when_no_tasks(self):
        with mock.patch("entrypoints.cli.check_emails", return_value=[]), \
             mock.patch("builtins.input", side_effect=["q"]):
            cli.interactive_loop()

    def test_create_task_from_text(self):
        outcome = tp.Outcome(ok=True, events=["开始处理任务"])

        with mock.patch("agent.user_agent.analyze_user_request",
                        return_value=ANALYSIS), \
             mock.patch("entrypoints.cli.process_task",
                        return_value=outcome):
            cli.create_task_from_text("我要报修宿舍水龙头")

        tasks = tm.load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["source"], "user")
        self.assertEqual(tasks[0]["subject"], "我要报修宿舍水龙头")

    def test_interact_waits_for_input_and_processes(self):
        """用户选择 WAITING_USER 任务并补充信息。"""
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], "WAITING_USER")

        outcome = tp.Outcome(ok=True, events=["用户输入已经保存"])

        with mock.patch("builtins.input", side_effect=[
                str(task["id"]),   # 选择任务
                "补充的信息",       # WAITING_USER 回复
                "q",               # 退出
        ]) as fake_input, \
             mock.patch("entrypoints.cli.continue_task",
                        return_value=outcome) as fake_continue:
            cli.interactive_loop()

        # 用户补充的信息被交给 continue_task
        fake_continue.assert_called_once_with(task["id"], "补充的信息")


class TestMainMenu(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_menu_quit(self):
        with mock.patch("builtins.input", side_effect=["q"]):
            cli.main_menu()

    def test_menu_choice_1_email(self):
        with mock.patch("builtins.input", side_effect=["1", "q"]), \
             mock.patch("entrypoints.cli.run_email_check") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_choice_2_repair(self):
        with mock.patch(
            "builtins.input",
            side_effect=["2", "我的宿舍卫生间水龙头坏了，需要维修", "q"],
        ), mock.patch("entrypoints.cli.create_task_from_text") as fake:
            cli.main_menu()

        fake.assert_called_once_with("我的宿舍卫生间水龙头坏了，需要维修")

    def test_menu_choice_3_tasks(self):
        with mock.patch("builtins.input", side_effect=["3", "q"]), \
             mock.patch("entrypoints.cli.list_tasks"), \
             mock.patch("entrypoints.cli.interactive_loop") as fake:
            cli.main_menu()

        fake.assert_called_once_with()

    def test_menu_unknown_choice(self):
        with mock.patch("builtins.input", side_effect=["x", "q"]):
            cli.main_menu()

    def test_menu_eof_exits_cleanly(self):
        """管道输入提前结束（EOF）时不抛异常。"""
        with mock.patch("builtins.input", side_effect=EOFError):
            cli.main_menu()


if __name__ == "__main__":
    unittest.main()

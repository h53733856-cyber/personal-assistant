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
                "w",               # 按 W 返回任务列表
                "q",               # 退出任务交互
        ]) as fake_input, \
             mock.patch("entrypoints.cli.continue_task",
                        return_value=outcome) as fake_continue:
            cli.interactive_loop()

        # 用户补充的信息被交给 continue_task
        fake_continue.assert_called_once_with(task["id"], "补充的信息")


class TestDriveTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def _repair_task(self, status, with_data=False):
        task = tm.create_user_task("报修", ANALYSIS)
        tm.update_task_status(task["id"], status)
        if with_data:
            tm.update_task_data(task["id"], "repair_data", {
                "SJH": "13800000000",
                "XMDM": "水龙头/水龙头漏水",
                "QYDM": "仙林校区",
                "GZDD": "某宿舍楼某房间",
                "DZ_FBSMKSSJ": "2026-09-20 19:00",
                "DZ_FBSMJSSJ": "2026-09-20 21:00",
                "GZMS": "水龙头坏了",
                "BZ": "",
                "GZTP": "",
                "DZ_SSDW": "1",
            })
        return task["id"]

    def test_waiting_user_w_returns_without_continue(self):
        tid = self._repair_task("WAITING_USER")

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.continue_task") as fake:
            cli.drive_task(tid)

        fake.assert_not_called()
        self.assertEqual(tm.get_task(tid)["status"], "WAITING_USER")

    def test_waiting_user_input_then_w(self):
        tid = self._repair_task("WAITING_USER")

        outcome = tp.Outcome(ok=True, events=["用户输入已经保存"])

        with mock.patch("builtins.input", side_effect=["补充的信息", "w"]), \
             mock.patch("entrypoints.cli.continue_task",
                        return_value=outcome) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid, "补充的信息")

    def test_waiting_confirmation_confirm(self):
        tid = self._repair_task("WAITING_CONFIRMATION", with_data=True)

        with mock.patch("builtins.input", side_effect=["确认"]), \
             mock.patch("entrypoints.cli.confirm_task",
                        return_value=tp.Outcome(ok=False, events=["失败"])) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid)

    def test_waiting_confirmation_w_keeps_state(self):
        tid = self._repair_task("WAITING_CONFIRMATION", with_data=True)

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.confirm_task") as fake_confirm, \
             mock.patch("entrypoints.cli.cancel_task") as fake_cancel:
            cli.drive_task(tid)

        fake_confirm.assert_not_called()
        fake_cancel.assert_not_called()
        self.assertEqual(tm.get_task(tid)["status"], "WAITING_CONFIRMATION")

    def test_new_task_auto_processed(self):
        tid = self._repair_task("NEW")

        with mock.patch("builtins.input", side_effect=["w"]), \
             mock.patch("entrypoints.cli.process_task",
                        return_value=tp.Outcome(ok=True, events=["处理中"])) as fake:
            cli.drive_task(tid)

        fake.assert_called_once_with(tid)

    def test_unknown_task(self):
        with mock.patch("builtins.input", side_effect=["w"]):
            cli.drive_task(999)


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

    def test_menu_choice_2_creates_and_drives_task(self):
        """创建任务后原地进入补充循环，而不是返回菜单。"""

        with mock.patch(
            "builtins.input",
            side_effect=["2", "空调坏了，需要维修", "w", "q"],
        ), mock.patch("entrypoints.cli.create_task_from_text",
                      return_value={"id": 1}), \
           mock.patch("entrypoints.cli.drive_task") as fake:
            cli.main_menu()

        fake.assert_called_once_with(1)

    def test_menu_unknown_choice(self):
        with mock.patch("builtins.input", side_effect=["x", "q"]):
            cli.main_menu()

    def test_menu_eof_exits_cleanly(self):
        """管道输入提前结束（EOF）时不抛异常。"""
        with mock.patch("builtins.input", side_effect=EOFError):
            cli.main_menu()


if __name__ == "__main__":
    unittest.main()

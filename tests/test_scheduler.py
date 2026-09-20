"""
entrypoints.scheduler 的恢复与自动处理测试（全部 mock）。
"""

import unittest
from unittest import mock

import agent.task_manager as tm
import agent.task_processor as tp
import entrypoints.scheduler as scheduler

from tests.helpers import TempDataDir


def fake_analysis():
    return {"type": "通知", "core": "x", "need_action": True, "action": "做某事"}


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def _task_with_status(self, status, **extra):
        task = tm.create_user_task("任务", fake_analysis())
        tm.update_task_status(task["id"], status)
        for key, value in extra.items():
            tm.update_task_data(task["id"], key, value)
        return task["id"]

    def test_recover_executing_interrupted(self):
        """EXECUTING 中中断（无成功结果）→ FAILED。"""
        tid = self._task_with_status("EXECUTING")

        scheduler.recover_interrupted_tasks()

        self.assertEqual(tm.get_task(tid)["status"], "FAILED")

    def test_recover_executing_failed_result(self):
        """EXECUTING 且 result.success=False → FAILED。"""
        tid = self._task_with_status(
            "EXECUTING",
            result={"at": "x", "success": False, "message": "失败"},
        )

        scheduler.recover_interrupted_tasks()

        self.assertEqual(tm.get_task(tid)["status"], "FAILED")

    def test_recover_executing_success_result(self):
        """EXECUTING 但 result.success=True（状态没来得及更新）→ COMPLETED。"""
        tid = self._task_with_status(
            "EXECUTING",
            result={"at": "x", "success": True, "message": "成功"},
        )

        scheduler.recover_interrupted_tasks()

        self.assertEqual(tm.get_task(tid)["status"], "COMPLETED")

    def test_recover_ignores_other_statuses(self):
        tid = self._task_with_status("WAITING_USER")

        scheduler.recover_interrupted_tasks()

        # 等待类状态不受影响（重启后不丢失）
        self.assertEqual(tm.get_task(tid)["status"], "WAITING_USER")

    def test_process_new_tasks(self):
        tid = self._task_with_status("NEW")

        with mock.patch("entrypoints.scheduler.process_task",
                        return_value=tp.Outcome(ok=True, events=["处理中"])) as fake:
            scheduler.process_new_tasks()

        fake.assert_called_once_with(tid)

    def test_run_once_flow(self):
        tid = self._task_with_status("NEW")

        with mock.patch("entrypoints.scheduler.check_emails",
                        return_value=[]), \
             mock.patch("entrypoints.scheduler.process_task",
                        return_value=tp.Outcome(ok=True, events=["处理中"])):
            scheduler.run_once()


if __name__ == "__main__":
    unittest.main()

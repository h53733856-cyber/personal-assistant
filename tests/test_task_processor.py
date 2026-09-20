"""
agent.task_processor 的流程测试。

LLM 与个人资料检索全部使用 mock，不消耗 API，
数据在临时目录中进行，不碰真实 tasks.json。

重点回归：continue_task 必须根据用户补充重新生成 repair_data。
"""

import unittest
from unittest import mock

import agent.task_manager as tm
import agent.task_processor as tp

from tests.helpers import TempDataDir

REPAIR_ANALYSIS = {
    "type": "宿舍报修",
    "core": "我的宿舍卫生间水龙头坏了，需要维修。",
    "time": None,
    "deadline": None,
    "need_action": True,
    "action": "在 EHALL 提交宿舍报修申请。",
}

GENERIC_ANALYSIS = {
    "type": "通知",
    "core": "阅读一份课程通知。",
    "need_action": False,
    "action": None,
}

# ---- mock 响应 ----

INFO_NO_PERSONAL = {
    "need_personal_info": False,
    "required_info": [],
    "available_info": [],
    "missing_info": [],
    "summary": "不需要个人信息",
}

INFO_MISSING = {
    "need_personal_info": True,
    "required_info": ["手机号", "宿舍地址", "报修类型"],
    "available_info": [],
    "missing_info": ["手机号", "宿舍地址", "报修类型"],
    "summary": "缺少信息",
}

INFO_COMPLETE = {
    "need_personal_info": True,
    "required_info": ["手机号", "宿舍地址"],
    "available_info": [
        {"info": "张三", "source": "profile.md"}
    ],
    "missing_info": [],
    "summary": "信息完整",
}

REPAIR_COMPLETE = {
    "phone": "13800000000",
    "repair_type": "水龙头/水龙头漏水",
    "area": "仙林校区",
    "location": "某宿舍楼某房间",
    "start_time": "2026-09-20 19:00",
    "end_time": "2026-09-20 21:00",
    "description": "卫生间水龙头坏了",
    "remark": "",
    "image": "",
}

REPAIR_INCOMPLETE = dict(REPAIR_COMPLETE, area="", repair_type="")

DECISION_CONFIRM = {
    "next_status": "WAITING_CONFIRMATION",
    "need_user_input": False,
    "question": None,
    "reason": "信息完整，需要确认",
}

DECISION_WAIT = {
    "next_status": "WAITING_USER",
    "need_user_input": True,
    "question": "请提供报修类型",
    "reason": "还缺信息",
}


def create_repair_task():
    email = {
        "message_id": "repair-test@mail",
        "subject": "【测试】宿舍报修",
        "sender": "test@example.com",
        "date": "2026-09-20",
    }
    return tm.create_task(email, REPAIR_ANALYSIS)


class TestProcessTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_task_not_found(self):
        out = tp.process_task(999)
        self.assertFalse(out.ok)
        self.assertIn("任务不存在", out.events[0])

    def test_no_personal_info_completed(self):
        task = tm.create_task(
            {
                "message_id": "m1", "subject": "通知",
                "sender": "a@b", "date": "2026-09-20",
            },
            GENERIC_ANALYSIS,
        )

        with mock.patch("agent.task_processor.ask_llm_json",
                        return_value=INFO_NO_PERSONAL):
            out = tp.process_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(tm.get_task(task["id"])["status"], "COMPLETED")

    def test_missing_info_waiting_user(self):
        task = create_repair_task()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[INFO_MISSING, REPAIR_INCOMPLETE],
        ):
            out = tp.process_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(tm.get_task(task["id"])["status"], "WAITING_USER")

    def test_repair_proceeds_despite_ai_misjudgment(self):
        """核心防护：报修任务即使被 AI 误判为不需要个人信息，
        也必须经过报修字段检查，不能直接 COMPLETED。"""
        task = create_repair_task()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[INFO_NO_PERSONAL, REPAIR_COMPLETE],
        ):
            out = tp.process_task(task["id"])

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["status"], "WAITING_CONFIRMATION")
        self.assertIsNotNone(saved["repair_data"])

    def test_repair_complete_waiting_confirmation(self):
        task = create_repair_task()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[INFO_COMPLETE, REPAIR_COMPLETE],
        ):
            out = tp.process_task(task["id"])

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["status"], "WAITING_CONFIRMATION")
        self.assertEqual(saved["repair_data"]["SJH"], "13800000000")
        self.assertEqual(saved["repair_data"]["QYDM"], "仙林校区")

        # 确认单快照必须已经生成，供 UI 在询问用户之前展示
        confirmation = saved["confirmation"]
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation["title"], "即将提交 EHALL 宿舍报修申请")
        labels = [f["label"] for f in confirmation["fields"]]
        self.assertIn("手机号", labels)
        self.assertIn("问题描述", labels)

    def test_repair_fields_incomplete_waiting_user(self):
        task = create_repair_task()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[INFO_COMPLETE, REPAIR_INCOMPLETE],
        ):
            out = tp.process_task(task["id"])

        self.assertEqual(tm.get_task(task["id"])["status"], "WAITING_USER")
        joined = "\n".join(out.events)
        self.assertIn("报修类型", joined)
        self.assertIn("报修区域", joined)

    def test_bad_llm_json_waiting_user(self):
        task = create_repair_task()

        with mock.patch("agent.task_processor.ask_llm_json",
                        side_effect=ValueError("bad json")):
            out = tp.process_task(task["id"])

        self.assertFalse(out.ok)
        self.assertEqual(tm.get_task(task["id"])["status"], "WAITING_USER")


class TestContinueTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def _task_waiting_user(self):
        task = create_repair_task()
        tm.update_task_status(task["id"], "WAITING_USER")
        return task

    def test_not_waiting_user(self):
        task = create_repair_task()
        out = tp.continue_task(task["id"], "补充信息")
        self.assertFalse(out.ok)

    def test_saves_user_input(self):
        task = self._task_waiting_user()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[REPAIR_COMPLETE, DECISION_CONFIRM],
        ):
            out = tp.continue_task(task["id"], "我住在仙林校区，电话13800000000")

        self.assertTrue(out.ok)
        saved = tm.get_task(task["id"])
        self.assertEqual(len(saved["user_inputs"]), 1)

    def test_regenerates_repair_data(self):
        """核心回归：用户补充后必须重新生成 repair_data，不能沿用旧数据。"""
        task = self._task_waiting_user()
        # 任务里存一份过期的 repair_data
        tm.update_task_data(
            task["id"], "repair_data",
            {"SJH": "旧数据", "QYDM": "旧数据"}
        )

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[REPAIR_COMPLETE, DECISION_CONFIRM],
        ):
            out = tp.continue_task(
                task["id"],
                "我住在仙林校区某宿舍楼某房间，水龙头漏水，手机号13800000000，"
                "今晚19:00到21:00方便维修。"
            )

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["repair_data"]["SJH"], "13800000000")
        self.assertEqual(saved["repair_data"]["QYDM"], "仙林校区")
        self.assertEqual(
            saved["repair_data"]["DZ_FBSMKSSJ"],
            "2026-09-20 19:00"
        )
        self.assertEqual(saved["status"], "WAITING_CONFIRMATION")
        self.assertIsNotNone(saved["confirmation"])

    def test_repair_still_incomplete_stays_waiting(self):
        task = self._task_waiting_user()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[REPAIR_INCOMPLETE, DECISION_CONFIRM],
        ):
            out = tp.continue_task(task["id"], "补充了一点信息")

        saved = tm.get_task(task["id"])
        self.assertEqual(saved["status"], "WAITING_USER")
        self.assertFalse(any("WAITING_CONFIRMATION" in e for e in out.events))

    def test_ai_decision_controls_next_status(self):
        task = self._task_waiting_user()

        with mock.patch(
            "agent.task_processor.ask_llm_json",
            side_effect=[REPAIR_COMPLETE, DECISION_WAIT],
        ):
            out = tp.continue_task(task["id"], "补充信息")

        self.assertEqual(tm.get_task(task["id"])["status"], "WAITING_USER")


class TestConfirmTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def _task_waiting_confirmation(self):
        task = create_repair_task()
        tm.update_task_status(task["id"], "WAITING_CONFIRMATION")
        tm.update_task_data(
            task["id"], "repair_data",
            {
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
            },
        )
        return task

    def test_not_waiting_confirmation(self):
        task = create_repair_task()
        out = tp.confirm_task(task["id"])
        self.assertFalse(out.ok)

    def test_repair_submit_failure_goes_failed(self):
        """EHALL 提交仍为模拟实现：失败进入 FAILED 终态，不再卡在 EXECUTING。"""
        task = self._task_waiting_confirmation()

        out = tp.confirm_task(task["id"])

        saved = tm.get_task(task["id"])

        self.assertFalse(out.ok)
        self.assertEqual(saved["status"], "FAILED")
        self.assertIn("尚未接入", saved["result"]["message"])
        self.assertFalse(saved["result"]["success"])
        # 执行结果被记录，重启后可以追溯
        self.assertIn("任务状态：FAILED", out.events)

    def test_generic_task_completed(self):
        email = {
            "message_id": "g1", "subject": "事务",
            "sender": "a@b", "date": "2026-09-20",
        }
        task = tm.create_task(email, {
            "type": "事务办理", "core": "普通事务",
            "need_action": True, "action": "办理",
        })
        tm.update_task_status(task["id"], "WAITING_CONFIRMATION")

        out = tp.confirm_task(task["id"])

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["status"], "COMPLETED")
        self.assertTrue(saved["result"]["success"])


class TestRequestConfirmation(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_generic_snapshot(self):
        email = {
            "message_id": "g2", "subject": "事务",
            "sender": "a@b", "date": "2026-09-20",
        }
        task = tm.create_task(email, {
            "type": "事务办理", "core": "办理某事",
            "need_action": True, "action": "填写表单",
        })

        out = tp.request_confirmation(task["id"])

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["status"], "WAITING_CONFIRMATION")
        self.assertEqual(saved["confirmation"]["title"], "即将执行任务")
        self.assertEqual(
            saved["confirmation"]["fields"][0]["value"],
            "办理某事"
        )

    def test_repair_without_data_goes_waiting(self):
        task = create_repair_task()

        out = tp.request_confirmation(task["id"])

        self.assertFalse(out.ok)
        self.assertEqual(tm.get_task(task["id"])["status"], "WAITING_USER")


class TestCancelTask(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()
        self._echo = tp.ECHO
        tp.ECHO = False

    def tearDown(self):
        tp.ECHO = self._echo
        self._ctx.__exit__(None, None, None)

    def test_cancel_from_confirmation(self):
        task = create_repair_task()
        tm.update_task_status(task["id"], "WAITING_CONFIRMATION")

        out = tp.cancel_task(task["id"])

        saved = tm.get_task(task["id"])

        self.assertTrue(out.ok)
        self.assertEqual(saved["status"], "CANCELLED")
        self.assertEqual(saved["result"]["message"], "用户取消任务")

    def test_cancel_terminal_rejected(self):
        task = create_repair_task()
        tm.update_task_status(task["id"], "COMPLETED")

        out = tp.cancel_task(task["id"])

        self.assertFalse(out.ok)
        self.assertEqual(tm.get_task(task["id"])["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()

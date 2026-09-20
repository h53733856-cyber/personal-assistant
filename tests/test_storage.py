"""
agent.task_manager 存储层的单元测试。

全部在临时目录中进行，不碰真实的 tasks/tasks.json。
"""

import threading
import unittest

import config
import agent.task_manager as tm

from tests.helpers import TempDataDir


def fake_email(i=1):
    return {
        "message_id": "mail-%d@test" % i,
        "subject": "主题 %d" % i,
        "sender": "sender%d@example.com" % i,
        "date": "2026-09-20",
    }


class TestTaskStorage(unittest.TestCase):

    def setUp(self):
        self._ctx = TempDataDir()
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_empty_load(self):
        self.assertEqual(tm.load_tasks(), [])

    def test_create_and_get(self):
        task = tm.create_task(fake_email(), {"type": "通知", "core": "x"})
        self.assertEqual(tm.get_task(task["id"])["subject"], "主题 1")

    def test_task_exists(self):
        tm.create_task(fake_email(1), {"core": "x"})
        self.assertTrue(tm.task_exists("mail-1@test"))
        self.assertFalse(tm.task_exists("mail-2@test"))

    def test_task_exists_with_user_tasks(self):
        """回归：任务列表里混有用户任务（没有 message_id）时不能崩溃。"""
        tm.create_user_task("报修任务", {"core": "x"})
        tm.create_task(fake_email(1), {"core": "x"})

        self.assertTrue(tm.task_exists("mail-1@test"))
        self.assertFalse(tm.task_exists("mail-2@test"))

    def test_update_status(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.update_task_status(task["id"], "PROCESSING")
        self.assertEqual(tm.get_task(task["id"])["status"], "PROCESSING")

    def test_update_data(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.update_task_data(task["id"], "repair_data", {"SJH": "1"})
        self.assertEqual(tm.get_task(task["id"])["repair_data"], {"SJH": "1"})

    def test_add_user_input(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.add_user_input(task["id"], "补充1")
        tm.add_user_input(task["id"], "补充2")
        self.assertEqual(
            tm.get_task(task["id"])["user_inputs"],
            ["补充1", "补充2"]
        )

    def test_get_new_and_user_tasks(self):
        t1 = tm.create_task(fake_email(1), {"core": "x"})
        t2 = tm.create_task(fake_email(2), {"core": "y"})
        tm.update_task_status(t2["id"], "WAITING_USER")

        self.assertEqual([t["id"] for t in tm.get_new_tasks()], [t1["id"]])
        self.assertEqual(len(tm.get_user_tasks()), 2)

    def test_concurrent_creates_unique_ids(self):
        """多线程并发创建任务，ID 不能重复。"""
        errors = []

        def create(i):
            try:
                tm.create_task(fake_email(i), {"core": "x"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        ids = [t["id"] for t in tm.load_tasks()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_atomic_write_no_tmp_left(self):
        tm.create_task(fake_email(), {"core": "x"})
        self.assertFalse(config.TASK_FILE.with_suffix(".tmp").exists())

    def test_new_task_has_model_fields(self):
        task = tm.create_task(fake_email(), {"core": "x"})

        self.assertEqual(task["source"], "email")
        self.assertIsNotNone(task["created_at"])
        self.assertEqual(len(task["history"]), 1)
        self.assertEqual(task["history"][0]["to"], "NEW")
        self.assertIsNone(task["confirmation"])
        self.assertIsNone(task["result"])

    def test_legacy_task_is_normalized(self):
        """旧格式任务（没有新字段）读取时自动补齐。"""
        legacy = [{
            "id": 1,
            "message_id": "old-1",
            "subject": "旧任务",
            "sender": "a@b.c",
            "date": "2026-09-01",
            "analysis": {"core": "x"},
            "status": "NEW",
        }]
        tm.save_tasks(legacy)

        task = tm.get_task(1)

        self.assertEqual(task["source"], "email")
        self.assertEqual(task["created_at"], "2026-09-01")
        self.assertEqual(task["history"], [])
        self.assertIsNone(task["confirmation"])
        self.assertIsNone(task["result"])

    def test_id_not_reused_after_delete(self):
        t1 = tm.create_task(fake_email(1), {"core": "x"})
        t2 = tm.create_task(fake_email(2), {"core": "y"})

        # 模拟删除任务 2
        remaining = [t for t in tm.load_tasks() if t["id"] != t2["id"]]
        tm.save_tasks(remaining)

        t3 = tm.create_task(fake_email(3), {"core": "z"})
        self.assertEqual(t3["id"], 3)
        self.assertIsNotNone(t1)

    def test_create_user_task(self):
        task = tm.create_user_task(
            "我要报修宿舍水龙头",
            {"type": "宿舍报修", "core": "报修水龙头", "need_action": True},
        )

        self.assertEqual(task["source"], "user")
        self.assertNotIn("message_id", task)
        self.assertEqual(task["subject"], "我要报修宿舍水龙头")
        self.assertEqual(task["status"], "NEW")
        self.assertEqual(tm.get_task(task["id"])["source"], "user")

    def test_clear_all_tasks_resets_ids(self):
        t1 = tm.create_user_task("任务1", {"core": "x"})
        t2 = tm.create_user_task("任务2", {"core": "x"})
        self.assertEqual(t2["id"], 2)

        tm.clear_all_tasks()

        self.assertEqual(tm.load_tasks(), [])

        # ID 计数器重置：新任务从 1 开始
        t3 = tm.create_user_task("任务3", {"core": "x"})
        self.assertEqual(t3["id"], 1)
        self.assertIsNotNone(t1)

    def test_history_records_transitions(self):
        task = tm.create_task(fake_email(), {"core": "x"})
        tm.update_task_status(task["id"], "PROCESSING", note="开始处理")
        tm.update_task_status(task["id"], "WAITING_USER", note="缺少信息")

        history = tm.get_task(task["id"])["history"]

        self.assertEqual(len(history), 3)
        self.assertEqual(history[1]["from"], "NEW")
        self.assertEqual(history[1]["to"], "PROCESSING")
        self.assertEqual(history[1]["note"], "开始处理")
        self.assertEqual(history[2]["from"], "PROCESSING")
        self.assertEqual(history[2]["to"], "WAITING_USER")


if __name__ == "__main__":
    unittest.main()

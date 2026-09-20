import json
import os
import threading
from datetime import datetime

import config

config.ensure_dirs()

# 所有读写操作共用一把锁，保证「读-改-写」过程原子，
# 邮件调度线程与 Web 请求并发时不会互相覆盖。
_lock = threading.RLock()


# --------------------------------------------------
# 底层读写
# --------------------------------------------------

def _now():
    return datetime.now().isoformat(timespec="seconds")


def _normalize(task):
    """给旧格式任务补上新字段（只在内存中补，写盘时才落盘）。"""

    task.setdefault("source", "email" if task.get("message_id") else "user")
    task.setdefault("created_at", task.get("date") or _now())
    task.setdefault("history", [])
    task.setdefault("confirmation", None)
    task.setdefault("result", None)

    return task


# 读取所有任务
def load_tasks():

    with _lock:

        if not os.path.exists(config.TASK_FILE):
            return []

        with open(config.TASK_FILE, "r", encoding="utf-8") as f:
            tasks = json.load(f)

        return [_normalize(t) for t in tasks]


# 保存所有任务（先写临时文件，再原子替换，避免写一半损坏）
def save_tasks(tasks):

    with _lock:

        config.TASKS_DIR.mkdir(parents=True, exist_ok=True)

        tmp_file = config.TASK_FILE.with_suffix(".tmp")

        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(
                tasks,
                f,
                ensure_ascii=False,
                indent=4
            )

        os.replace(tmp_file, config.TASK_FILE)


# --------------------------------------------------
# 任务读写
# --------------------------------------------------

def _next_id(tasks):
    """分配下一个任务 ID。

    使用持久化计数器，删除任务后也不会复用 ID。
    计数器文件丢失时，从已有任务的最大 ID 恢复。
    """

    counter_file = config.TASKS_DIR / "next_id.txt"

    if os.path.exists(counter_file):
        with open(counter_file, "r", encoding="utf-8") as f:
            next_id = int(f.read().strip())
    else:
        next_id = max((t["id"] for t in tasks), default=0) + 1

    # 先预留 ID 再写任务：即使任务保存失败，也只是留下空洞，不会重复
    with open(counter_file, "w", encoding="utf-8") as f:
        f.write(str(next_id + 1))

    return next_id


def _new_task(subject, source, analysis, email=None):
    """构造一个统一格式的任务记录。

    source: "email"（邮件触发）或 "user"（用户主动发起）。
    email:  邮件字典，仅 source 为 "email" 时传入。
    """

    now = _now()

    task = {
        "id": None,  # 由调用方分配
        "source": source,
        "subject": subject,
        "analysis": analysis,
        "status": "NEW",
        "created_at": now,
        "history": [
            {
                "at": now,
                "from": None,
                "to": "NEW",
                "note": "创建任务"
            }
        ],
        "confirmation": None,
        "result": None,
    }

    if email is not None:
        task["message_id"] = email["message_id"]
        task["sender"] = email["sender"]
        task["date"] = email["date"]

    return task


# 根据邮件创建一个新任务
def create_task(email, analysis):

    with _lock:

        tasks = load_tasks()

        task = _new_task(
            subject=email["subject"],
            source="email",
            analysis=analysis,
            email=email,
        )

        task["id"] = _next_id(tasks)

        tasks.append(task)

        save_tasks(tasks)

        return task


# 根据用户主动请求创建一个新任务（无邮件信息）
def create_user_task(subject, analysis):

    with _lock:

        tasks = load_tasks()

        task = _new_task(
            subject=subject,
            source="user",
            analysis=analysis,
        )

        task["id"] = _next_id(tasks)

        tasks.append(task)

        save_tasks(tasks)

        return task


# 返回某封邮件对应的所有任务
def get_tasks_by_message_id(message_id):

    return [
        t for t in load_tasks()
        if t.get("message_id") == message_id
    ]


# 判断某封邮件是否已经创建过任务
def task_exists(message_id):

    tasks = load_tasks()

    for task in tasks:

        # tasks.json 里面有没有同一个 message_id
        if task["message_id"] == message_id:
            return True

    return False


# 获取所有 NEW 状态的任务
def get_new_tasks():
    tasks = load_tasks()
    new_tasks = []

    for task in tasks:
        if task["status"] == "NEW":
            new_tasks.append(task)

    return new_tasks


def get_user_tasks():
    tasks = load_tasks()
    user_tasks = []

    for task in tasks:
        if task["status"] == "NEW" \
                or task["status"] == "WAITING_USER" \
                or task["status"] == "WAITING_CONFIRMATION":

            user_tasks.append(task)

    return user_tasks


# 根据任务 ID 获取任务
def get_task(task_id):

    tasks = load_tasks()

    for task in tasks:

        if task["id"] == task_id:
            return task

    return None


# 修改任务状态（同时记录状态变迁历史）
def update_task_status(task_id, status, note=None):

    with _lock:

        tasks = load_tasks()

        for task in tasks:

            if task["id"] == task_id:

                old_status = task["status"]
                task["status"] = status
                task["history"].append({
                    "at": _now(),
                    "from": old_status,
                    "to": status,
                    "note": note,
                })

                save_tasks(tasks)

                return True

    return False


def update_task_data(task_id, key, value):

    with _lock:

        tasks = load_tasks()

        for task in tasks:
            if task["id"] == task_id:
                task[key] = value
                save_tasks(tasks)
                return True

    return False


# 给任务保存用户输入
def add_user_input(task_id, user_input):

    with _lock:

        tasks = load_tasks()

        for task in tasks:

            if task["id"] == task_id:

                # 如果还没有 user_inputs，就创建一个空列表
                if "user_inputs" not in task:
                    task["user_inputs"] = []

                # 保存用户输入
                task["user_inputs"].append(user_input)

                save_tasks(tasks)

                return True

    return False


def clear_all_tasks():
    """清空所有任务，任务 ID 计数器重置为 1。"""

    with _lock:

        save_tasks([])

        counter_file = config.TASKS_DIR / "next_id.txt"

        with open(counter_file, "w", encoding="utf-8") as f:
            f.write("1")

    return True


def create_test_task():

    with _lock:

        tasks = load_tasks()

        task = _new_task(
            subject="【测试】EHALL申请提交",
            source="email",
            analysis={
                "type": "事务办理",
                "core": "需要在EHALL提交一份申请。",
                "time": None,
                "deadline": None,
                "need_action": True,
                "action": "填写申请表并提交。"
            },
            email={
                "message_id": "test-" + str(_next_id(tasks)),
                "sender": "test@example.com",
                "date": "2026-09-19",
            },
        )

        task["id"] = _next_id(tasks)

        tasks.append(task)

        save_tasks(tasks)

        return task

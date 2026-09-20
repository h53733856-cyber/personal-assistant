import json
import os

import config

config.ensure_dirs()


# 读取所有任务
def load_tasks():

    if not os.path.exists(config.TASK_FILE):
        return []

    with open(config.TASK_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# 保存所有任务
def save_tasks(tasks):

    with open(config.TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(
            tasks,
            f,
            ensure_ascii=False,
            indent=4
        )


# 创建一个新任务
def create_task(email, analysis):

    tasks = load_tasks()

    task = {
        "id": len(tasks) + 1,
        "message_id": email["message_id"],
        "subject": email["subject"],
        "sender": email["sender"],
        "date": email["date"],
        "analysis": analysis,
        "status": "NEW"
    }

    tasks.append(task)

    save_tasks(tasks)

    return task


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


# 修改任务状态
def update_task_status(task_id, status):

    tasks = load_tasks()

    for task in tasks:

        if task["id"] == task_id:

            task["status"] = status

            save_tasks(tasks)

            return True

    return False


def update_task_data(task_id, key, value):
    tasks = load_tasks()

    for task in tasks:
        if task["id"] == task_id:
            task[key] = value
            save_tasks(tasks)
            return True

    return False

# 给任务保存用户输入
def add_user_input(task_id, user_input):

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


def create_test_task():
    tasks = load_tasks()

    task = {
        "id": len(tasks) + 1,
        "message_id": "test-" + str(len(tasks) + 1),
        "subject": "【测试】EHALL申请提交",
        "sender": "test@example.com",
        "date": "2026-09-19",
        "analysis": {
            "type": "事务办理",
            "core": "需要在EHALL提交一份申请。",
            "time": None,
            "deadline": None,
            "need_action": True,
            "action": "填写申请表并提交。"
        },
        "status": "NEW"
    }

    tasks.append(task)
    save_tasks(tasks)

    return task
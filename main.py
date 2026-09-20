"""
Personal Assistant 主入口（命令行交互模式）。

邮件处理已经移入 services/email_service.py，
这里只负责调用并展示结果，业务逻辑不依赖 input()。
"""

from agent.task_processor import (
    process_task,
    continue_task,
    confirm_task,
    cancel_task
)

from agent.task_manager import (
    get_task,
    get_user_tasks
)

from services.email_service import check_emails


print("Personal Assistant started!")


# ==============================
# 第一步：读取并分析最近邮件
# ==============================

events = check_emails()

for line in events:
    print(line)


# ==============================
# 第二步：查看当前需要处理的任务
# ==============================

print()
print("================================")
print("当前需要用户处理的任务：")

user_tasks = get_user_tasks()

for task in user_tasks:

    print()
    print("任务 ID：", task["id"])
    print("任务主题：", task["subject"])
    print("任务内容：", task["analysis"]["core"])
    print("任务状态：", task["status"])


# ==============================
# 第三步：用户与任务交互
# ==============================

print()
print("================================")
print("任务交互")

while True:

    # 每次循环都重新读取任务
    user_tasks = get_user_tasks()

    if len(user_tasks) == 0:

        print("当前没有需要处理的任务。")
        break

    print()
    print("当前需要用户处理的任务：")

    for task in user_tasks:

        print()
        print("任务 ID：", task["id"])
        print("任务主题：", task["subject"])
        print("任务内容：", task["analysis"]["core"])
        print("任务状态：", task["status"])

    print()

    # 让用户选择任务
    task_id_input = input("请输入任务 ID（输入 q 退出）：")

    if task_id_input == "q":

        print("退出任务交互。")
        break

    # 把用户输入的任务 ID 转换成整数
    try:
        task_id = int(task_id_input)
    except ValueError:

        print("无法识别你的输入。")
        continue

    # 获取任务最新状态
    task = get_task(task_id)

    if task is None:

        print("任务不存在。")
        continue

    # ==============================
    # WAITING_USER
    # ==============================

    if task["status"] == "WAITING_USER":

        print()
        print("这个任务正在等待你的信息。")

        user_input = input("请输入你的回复：")

        continue_task(task_id, user_input)

    # ==============================
    # WAITING_CONFIRMATION
    # ==============================

    elif task["status"] == "WAITING_CONFIRMATION":

        print()
        print("这个任务需要你的确认。")

        # 先展示确认单（关键字段 + 可能后果），再询问用户
        confirmation = task.get("confirmation")

        if confirmation:

            print()
            print("================================")
            print(confirmation["title"])
            print("================================")

            for field in confirmation["fields"]:
                print(field["label"] + "：" + str(field["value"]))

            print()
            print("注意：" + confirmation["warning"])
            print("================================")

        else:

            print("任务内容：", task["analysis"]["core"])

        confirm_input = input("请输入“确认”或“取消”：")

        if confirm_input == "确认":

            confirm_task(task_id)

        elif confirm_input == "取消":

            print("用户取消了任务。")

            cancel_task(task_id)

        else:

            print("无法识别你的输入，任务暂不执行。")

    # ==============================
    # NEW
    # ==============================

    elif task["status"] == "NEW":

        print()
        print("这个任务还没有开始处理。")

        process_task(task_id)

    # ==============================
    # 其他状态
    # ==============================

    else:

        print()
        print("当前任务状态：", task["status"])

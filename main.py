from tools.email import get_recent_emails

# 去 email.py 找读取邮件的功能

from agent.email_agent import analyze_email

# 去 email_agent.py 找邮件分析功能

from agent.task_processor import (
    continue_task,
    confirm_task,
    cancel_task
)

from agent.task_manager import (
    create_task,
    task_exists,
    get_new_tasks,
    get_user_tasks
)

# 去 task_manager.py 找任务管理功能


print("Personal Assistant started!")


# ==============================
# 第一步：读取最近邮件
# ==============================

emails = get_recent_emails()


# ==============================
# 第二步：处理邮件
# ==============================

for mail in emails:

    print()
    print("================================")
    print("主题：", mail["subject"])
    print("发件人：", mail["sender"])
    print("时间：", mail["date"])

    # 先检查这封邮件以前是否已经处理过
    if task_exists(mail["message_id"]):

        print()
        print("这封邮件已经处理过，跳过 AI 分析。")

        continue

    # ==============================
    # 调用 AI 分析邮件
    # ==============================

    print()
    print("AI 分析：")

    result = analyze_email(mail)

    print("邮件类型：", result["type"])
    print("核心事项：", result["core"])
    print("时间信息：", result["time"])
    print("截止时间：", result["deadline"])
    print("需要用户行动：", result["need_action"])
    print("需要做什么：", result["action"])

    # ==============================
    # 如果需要用户行动，就创建任务
    # ==============================

    if result["need_action"]:

        task = create_task(mail, result)

        print()
        print("已创建任务：", task["id"])


# ==============================
# 第三步：查看当前 NEW 任务
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
# 第四步：用户与任务交互
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
    task_id = int(task_id_input)

    # 获取任务最新状态
    from agent.task_manager import get_task

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

        # 这里暂时只把任务交给 Agent 处理
        from agent.task_processor import process_task

        process_task(task_id)

    # ==============================
    # 其他状态
    # ==============================

    else:

        print()
        print("当前任务状态：", task["status"])
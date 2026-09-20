"""
命令行入口。

业务逻辑全部来自 service / agent 层，本文件只负责输入输出。
CLI 与 Web API 调用同一批 service 函数，互不影响。
"""

import sys
from pathlib import Path

# 保证从任何目录运行都能找到项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import agent.task_processor as processor
import agent.task_manager as task_manager
from services.agent_service import (
    process_task,
    continue_task,
    confirm_task,
    cancel_task,
    get_missing_repair_fields,
)
from services.email_service import check_emails

# CLI 自己渲染事件，关闭处理器内部的终端打印
processor.ECHO = False


def _print_outcome(outcome):
    for line in outcome.events:
        print(line)


def _ask(prompt):
    """input() 的包装：管道输入结束（EOF）时返回 None，不会抛异常。"""

    try:
        return input(prompt)
    except EOFError:
        return None


def run_email_check():
    print()
    print("Personal Assistant started!")
    print()

    events = check_emails()

    for line in events:
        print(line)


def list_tasks():
    print()
    print("================================")
    print("当前需要用户处理的任务：")

    for task in task_manager.get_user_tasks():
        print()
        print("任务 ID：", task["id"])
        print("任务主题：", task["subject"])
        print("任务内容：", task["analysis"]["core"])
        print("任务状态：", task["status"])


def create_task_from_text(text):
    """分析用户请求并创建任务，返回最新任务（或 None）。"""

    from agent.user_agent import analyze_user_request

    print()
    print("正在分析你的请求...")

    analysis = analyze_user_request(text)

    print("请求类型：", analysis["type"])
    print("核心事项：", analysis["core"])
    print("需要用户行动：", analysis["need_action"])

    if not analysis.get("need_action"):
        print("这个请求不需要创建任务。")
        return None

    task = task_manager.create_user_task(text, analysis)

    print()
    print("已创建任务：", task["id"])
    print()

    _print_outcome(process_task(task["id"]))

    return task_manager.get_task(task["id"])


def drive_task(task_id):
    """连续引导一个任务直到结束：

    - 缺信息：直接在这里补充（按 W 返回菜单）
    - 要确认：先展示确认单再询问
    - NEW：自动开始处理
    """

    while True:

        task = task_manager.get_task(task_id)

        if task is None:

            print("任务不存在。")
            return

        status = task["status"]

        # ==============================
        # 等待用户补充信息：原地询问
        # ==============================

        if status == "WAITING_USER":

            print()
            print("这个任务正在等待你的信息。")

            missing = get_missing_repair_fields(task)

            if missing:

                print()
                print("还缺少以下信息：")

                for name in missing:
                    print("- " + name)

            print()
            user_input = _ask("请直接输入补充信息（按 W 返回菜单）：")

            if user_input is None or user_input.strip().lower() == "w":

                print("任务保持等待状态，稍后可以在任务中心继续。")
                return

            if user_input.strip():
                _print_outcome(continue_task(task_id, user_input.strip()))

            continue

        # ==============================
        # 等待用户确认：先展示确认单
        # ==============================

        if status == "WAITING_CONFIRMATION":

            print()
            print("这个任务需要你的确认。")

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

            confirm_input = _ask("请输入“确认”或“取消”（按 W 返回菜单）：")

            if confirm_input == "确认":

                _print_outcome(confirm_task(task_id))
                return

            if confirm_input == "取消":

                print("用户取消了任务。")

                _print_outcome(cancel_task(task_id))
                return

            if confirm_input is None or confirm_input.strip().lower() == "w":
                return

            print("无法识别你的输入，任务暂不执行。")
            continue

        # ==============================
        # 还没开始处理：自动开始
        # ==============================

        if status == "NEW":

            print()
            print("这个任务还没有开始处理。")

            _print_outcome(process_task(task_id))

            # 如果处理没有让状态前进（异常情况），不再无限循环
            task = task_manager.get_task(task_id)

            if task and task["status"] == "NEW":

                print("任务处理没有推进，请稍后在任务中心重试。")
                return

            continue

        # ==============================
        # 其他状态（终态）
        # ==============================

        print()
        print("当前任务状态：", status)
        return


def record_feedback_from_cli(text, commit=False):
    from agent.growth import record_feedback

    path = record_feedback(text, commit=commit)

    print("反馈已记录：", path)
    print("Agent 之后的任务会遵守这条规则。")


def interactive_loop():
    """任务交互循环（原 main.py 的交互部分）。"""

    print()
    print("================================")
    print("任务交互")

    while True:

        user_tasks = task_manager.get_user_tasks()

        if len(user_tasks) == 0:

            print()
            print("当前没有需要处理的任务。")
            return

        print()
        print("当前需要用户处理的任务：")

        for task in user_tasks:

            print()
            print("任务 ID：", task["id"])
            print("任务主题：", task["subject"])
            print("任务内容：", task["analysis"]["core"])
            print("任务状态：", task["status"])

        print()

        task_id_input = _ask(
            "输入任务 ID 处理；输入 new 创建新任务；输入 q 返回："
        )

        if task_id_input is None or task_id_input == "q":

            print("退出任务交互。")
            return

        if task_id_input == "new":

            text = _ask("请输入你的请求：")

            if text and text.strip():
                create_task_from_text(text.strip())

            continue

        try:
            task_id = int(task_id_input)
        except ValueError:

            print("无法识别你的输入。")
            continue

        task = task_manager.get_task(task_id)

        if task is None:

            print("任务不存在。")
            continue

        # 交给 drive_task 连续引导：缺信息原地补、确认单先展示，
        # 按 W 回到任务列表
        drive_task(task_id)


def main_menu():
    """主菜单：一个命令进来，选择要用的功能，选哪个自动运行哪个。"""

    while True:

        print()
        print("========================================")
        print("个人助手")
        print("========================================")
        print("1. 邮件服务：检查 smail，AI 分析并自动创建任务")
        print("2. 宿舍报修：发起 EHALL 报修任务")
        print("3. 任务中心：查看任务、补充信息、确认执行")
        print("q. 退出")
        print()

        choice = _ask("请选择功能：")

        if choice is None or choice == "q":

            print("再见！")
            return

        if choice == "1":

            run_email_check()

        elif choice == "2":

            text = _ask(
                "请描述报修内容（例如：我的宿舍卫生间水龙头坏了，需要维修）："
            )

            if not text or not text.strip():

                print("没有输入内容，返回菜单。")

            else:

                task = create_task_from_text(text.strip())

                if task:
                    # 缺什么信息直接在这里补充，按 W 返回菜单
                    drive_task(task["id"])

        elif choice == "3":

            list_tasks()
            interactive_loop()

        else:

            print("无法识别你的输入，请重新选择。")


def main():
    parser = argparse.ArgumentParser(description="Personal Assistant 命令行入口")

    parser.add_argument(
        "command",
        nargs="?",
        default="menu",
        choices=["menu", "email", "tasks", "new", "feedback"],
        help="menu=功能主菜单（默认）；email=直接运行邮件服务；"
             "tasks=列出任务；new=直接创建任务；feedback=记录一条用户纠正/偏好",
    )
    parser.add_argument("text", nargs="*", help="new / feedback 命令的内容")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="feedback 时自动 git 提交",
    )

    args = parser.parse_args()

    if args.command == "menu":
        main_menu()
    elif args.command == "email":
        run_email_check()
    elif args.command == "tasks":
        list_tasks()
    elif args.command == "new":
        text = " ".join(args.text)
        if not text:
            print("请提供任务描述，例如：python main.py new 我要报修宿舍水龙头")
            return
        create_task_from_text(text)
    elif args.command == "feedback":
        text = " ".join(args.text)
        if not text:
            print("请提供反馈内容，例如：python main.py feedback 报修时间格式要统一")
            return
        record_feedback_from_cli(text, commit=args.commit)


if __name__ == "__main__":
    main()

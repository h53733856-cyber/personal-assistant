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
)
from services.email_service import check_emails

# CLI 自己渲染事件，关闭处理器内部的终端打印
processor.ECHO = False


def _print_outcome(outcome):
    for line in outcome.events:
        print(line)


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
    from agent.user_agent import analyze_user_request

    print()
    print("正在分析你的请求...")

    analysis = analyze_user_request(text)

    print("请求类型：", analysis["type"])
    print("核心事项：", analysis["core"])
    print("需要用户行动：", analysis["need_action"])

    if not analysis.get("need_action"):
        print("这个请求不需要创建任务。")
        return

    task = task_manager.create_user_task(text, analysis)

    print()
    print("已创建任务：", task["id"])
    print()

    _print_outcome(process_task(task["id"]))


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

        task_id_input = input(
            "输入任务 ID 处理；输入 new 创建新任务；输入 q 退出："
        )

        if task_id_input == "q":

            print("退出任务交互。")
            return

        if task_id_input == "new":

            text = input("请输入你的请求：")

            if text.strip():
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

        # ==============================
        # WAITING_USER
        # ==============================

        if task["status"] == "WAITING_USER":

            print()
            print("这个任务正在等待你的信息。")

            user_input = input("请输入你的回复：")

            _print_outcome(continue_task(task_id, user_input))

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

                _print_outcome(confirm_task(task_id))

            elif confirm_input == "取消":

                print("用户取消了任务。")

                _print_outcome(cancel_task(task_id))

            else:

                print("无法识别你的输入，任务暂不执行。")

        # ==============================
        # NEW
        # ==============================

        elif task["status"] == "NEW":

            print()
            print("这个任务还没有开始处理。")

            _print_outcome(process_task(task_id))

        # ==============================
        # 其他状态
        # ==============================

        else:

            print()
            print("当前任务状态：", task["status"])


def main():
    parser = argparse.ArgumentParser(description="Personal Assistant 命令行入口")

    parser.add_argument(
        "command",
        nargs="?",
        default="interact",
        choices=["interact", "email", "tasks", "new"],
        help="interact=检查邮件并进入任务交互（默认）；"
             "email=只检查邮件；tasks=列出任务；new=创建新任务",
    )
    parser.add_argument("text", nargs="*", help="new 命令的任务描述")

    args = parser.parse_args()

    if args.command == "email":
        run_email_check()
    elif args.command == "tasks":
        list_tasks()
    elif args.command == "new":
        text = " ".join(args.text)
        if not text:
            print("请提供任务描述，例如：python main.py new 我要报修宿舍水龙头")
            return
        create_task_from_text(text)
    else:
        # 默认：与旧 main.py 一致——先检查邮件，再进入任务交互
        run_email_check()
        list_tasks()
        interactive_loop()


if __name__ == "__main__":
    main()

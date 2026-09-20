"""
手机端 Web 入口。

- REST API（/api/*）供手机页面调用
- 托管 web/index.html 移动端页面
- 后台线程运行调度器（拉邮件 + 自动处理 NEW 任务 + 启动恢复）

用法：
    python server.py              # 监听 0.0.0.0:5000
    PA_PORT=8080 python server.py
"""

import os
import sys
import threading
from pathlib import Path

# 保证从任何目录运行都能找到项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging

import config
import agent.task_processor as processor
import agent.task_manager as task_manager
from services.agent_service import (
    process_task,
    continue_task,
    confirm_task,
    cancel_task,
)
from services.email_service import check_emails
from flask import Flask, jsonify, request, send_from_directory

# 服务器模式：处理器事件不打印到终端，统一走日志
processor.ECHO = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("server")

app = Flask(__name__, static_folder="web", static_url_path="")


# --------------------------------------------------
# 页面
# --------------------------------------------------

@app.get("/")
def index():
    return send_from_directory("web", "index.html")


# --------------------------------------------------
# API
# --------------------------------------------------

def _task_summary(task):
    return {
        "id": task["id"],
        "subject": task["subject"],
        "status": task["status"],
        "source": task.get("source"),
        "core": (task.get("analysis") or {}).get("core"),
        "created_at": task.get("created_at"),
    }


@app.get("/api/tasks")
def list_tasks():
    tasks = sorted(
        task_manager.load_tasks(),
        key=lambda t: t["id"],
        reverse=True,
    )
    return jsonify([_task_summary(t) for t in tasks])


@app.post("/api/tasks")
def create_task():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "message": "任务内容不能为空"}), 400

    from agent.user_agent import analyze_user_request

    try:
        analysis = analyze_user_request(text)
    except Exception as e:
        log.exception("用户请求分析失败")
        return jsonify({"ok": False, "message": "AI 分析失败：" + str(e)}), 502

    if not analysis.get("need_action"):
        return jsonify({"ok": True, "created": False, "analysis": analysis})

    task = task_manager.create_user_task(text, analysis)
    outcome = process_task(task["id"])

    return jsonify({
        "ok": True,
        "created": True,
        "task": task_manager.get_task(task["id"]),
        "events": outcome.events,
    })


@app.get("/api/tasks/<int:task_id>")
def get_task(task_id):
    task = task_manager.get_task(task_id)

    if task is None:
        return jsonify({"ok": False, "message": "任务不存在"}), 404

    return jsonify(task)


@app.post("/api/tasks/<int:task_id>/input")
def task_input(task_id):
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "message": "内容不能为空"}), 400

    outcome = continue_task(task_id, text)

    return jsonify({
        "ok": outcome.ok,
        "events": outcome.events,
        "task": task_manager.get_task(task_id),
    })


@app.post("/api/tasks/<int:task_id>/confirm")
def task_confirm(task_id):
    outcome = confirm_task(task_id)

    return jsonify({
        "ok": outcome.ok,
        "events": outcome.events,
        "task": task_manager.get_task(task_id),
    })


@app.post("/api/tasks/<int:task_id>/cancel")
def task_cancel(task_id):
    outcome = cancel_task(task_id)

    return jsonify({
        "ok": outcome.ok,
        "events": outcome.events,
        "task": task_manager.get_task(task_id),
    })


@app.post("/api/emails/check")
def emails_check():
    events = check_emails()
    return jsonify({"ok": True, "events": events})


# --------------------------------------------------
# 启动
# --------------------------------------------------

def start_scheduler_thread():
    from entrypoints.scheduler import run_forever

    thread = threading.Thread(
        target=run_forever,
        args=(config.EMAIL_POLL_INTERVAL,),
        daemon=True,
        name="scheduler",
    )
    thread.start()
    log.info("后台调度线程已启动，间隔 %d 秒", config.EMAIL_POLL_INTERVAL)


def main():
    port = int(os.getenv("PA_PORT", "5000"))
    start_scheduler_thread()
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

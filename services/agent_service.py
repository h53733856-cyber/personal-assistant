"""
Agent 核心的对外服务层。

入口层（CLI / Web / 调度器）只调用这里，
不直接依赖 task_processor 的实现细节。
"""

from agent.task_processor import (
    process_task,
    continue_task,
    confirm_task,
    cancel_task,
    request_confirmation,
    get_missing_repair_fields,
)

__all__ = [
    "process_task",
    "continue_task",
    "confirm_task",
    "cancel_task",
    "request_confirmation",
    "get_missing_repair_fields",
]

"""
Agent 任务处理核心。

职责：
- NEW 任务的分析与处理（process_task）
- WAITING_USER 任务的继续处理（continue_task）
- WAITING_CONFIRMATION 任务的执行（confirm_task）

设计：
- 本模块不直接与用户交互（不调用 input()）。
- 用户可见的消息通过 Outcome.events 返回，由入口层（CLI / Web）负责展示。
- ECHO 为 True 时（默认），事件会同步打印到终端，保证命令行体验不变；
  服务端（Web / 调度器）把 ECHO 关掉即可拿到干净的事件流。
"""

from dataclasses import dataclass, field
from datetime import datetime

from tools.personal_db import search_documents
from agent.llm import ask_llm_json
from agent.task_manager import (
    get_task,
    update_task_status,
    add_user_input,
    update_task_data
)

# 为 True 时，事件会同步打印到终端（保持原有 CLI 输出体验）
ECHO = True

# 宿舍报修必填字段（EHALL 字段码 -> 中文名）
REQUIRED_REPAIR_FIELDS = {
    "SJH": "手机号",
    "XMDM": "报修类型",
    "QYDM": "报修区域",
    "GZDD": "详细地点",
    "DZ_FBSMKSSJ": "上门服务开始时间",
    "DZ_FBSMJSSJ": "上门服务结束时间",
    "GZMS": "问题描述"
}

# 确认单中要展示的报修字段（顺序固定，便于阅读）
REPAIR_CONFIRM_FIELDS = [
    ("SJH", "手机号"),
    ("XMDM", "报修类型"),
    ("QYDM", "报修区域"),
    ("GZDD", "详细地点"),
    ("DZ_FBSMKSSJ", "上门服务开始时间"),
    ("DZ_FBSMJSSJ", "上门服务结束时间"),
    ("GZMS", "问题描述"),
    ("BZ", "备注"),
]


def _now():
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Outcome:
    """Agent 处理结果：ok + 用户可见事件列表 + 结构化数据。"""

    ok: bool = True
    events: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def emit(self, message=""):
        """记录一条用户可见消息；ECHO 打开时同步打印。"""

        self.events.append(message)

        if ECHO:
            print(message)


# --------------------------------------------------
# 小工具
# --------------------------------------------------

def _format_user_inputs(user_inputs):
    text = ""

    for i, user_input in enumerate(user_inputs):
        text += f"{i + 1}. {user_input}\n"

    return text


def _format_personal_info(results):
    personal_info = ""

    for result in results:
        personal_info += (
            "\n文件：" + result["file"] +
            "\n内容：\n" + result["content"] +
            "\n"
        )

    return personal_info


# --------------------------------------------------
# 宿舍报修字段提取（process_task 与 continue_task 共用，
# 避免同一份逻辑写两遍）
# --------------------------------------------------

def _extract_repair_fields(core, user_input_text, personal_info=""):
    """让 AI 从任务内容、个人资料、用户补充中提取报修字段。"""

    prompt = f"""
你是我的个人助手。

现在需要准备一份南京大学 EHALL 宿舍报修申请。

任务内容：
{core}

我的个人资料：
{personal_info}

用户已经补充的信息：
{user_input_text}

请从以上内容中提取宿舍报修表单需要的信息。

需要的字段：

1. phone
   手机号

2. repair_type
   报修类型

3. area
   报修区域

4. location
   详细地点

5. start_time
   上门服务开始时间
   格式：yyyy-MM-dd HH:mm

6. end_time
   上门服务结束时间
   格式：yyyy-MM-dd HH:mm

7. description
   问题描述

8. remark
   备注，没有则为空字符串

9. image
   故障图片，没有则为空字符串

严格要求：

1. 只能使用任务内容、个人资料和用户已经提供的信息。
2. 不允许编造任何字段。
3. 无法确定的字段必须返回空字符串。
4. 时间必须尽量转换成 yyyy-MM-dd HH:mm。
5. 如果用户没有提供具体时间，不要自行猜测。
6. 报修类型和报修区域如果无法确定，也不要自行猜测。
7. description 可以使用任务内容中明确描述的问题。
8. 只返回 JSON，不要添加 Markdown 或解释。

严格按照下面格式返回：

{{
    "phone": "",
    "repair_type": "",
    "area": "",
    "location": "",
    "start_time": "",
    "end_time": "",
    "description": "",
    "remark": "",
    "image": ""
}}
"""

    return ask_llm_json(prompt)


def _build_repair_data(repair_fields):
    """把 AI 提取的字段构造成 EHALL 报修数据。"""

    from tools.ehall import build_repair_data

    return build_repair_data(
        phone=repair_fields.get("phone", ""),
        repair_type=repair_fields.get("repair_type", ""),
        area=repair_fields.get("area", ""),
        location=repair_fields.get("location", ""),
        start_time=repair_fields.get("start_time", ""),
        end_time=repair_fields.get("end_time", ""),
        description=repair_fields.get("description", ""),
        remark=repair_fields.get("remark", ""),
        image=repair_fields.get("image", "")
    )


def _check_repair_fields(repair_data):
    """检查报修必填字段，返回缺失字段的中文名列表。"""

    missing = []

    for key, name in REQUIRED_REPAIR_FIELDS.items():
        if not repair_data.get(key):
            missing.append(name)

    return missing


def _missing_repair_fields_to_waiting(out, task_id, repair_data):
    """报修字段不完整时，更新状态并输出事件；返回是否缺失。"""

    missing = _check_repair_fields(repair_data)

    if len(missing) == 0:
        return False

    update_task_status(task_id, "WAITING_USER", note="报修信息不完整")

    out.emit()
    out.emit("宿舍报修还缺少以下信息：")

    for field in missing:
        out.emit("- " + field)

    out.emit()
    out.emit("任务状态：WAITING_USER")

    return True


# --------------------------------------------------
# 处理 NEW 任务
# --------------------------------------------------

def process_task(task_id):
    out = Outcome()

    task = get_task(task_id)

    if task is None:
        out.ok = False
        out.emit("任务不存在。")
        return out

    out.emit("开始处理任务：" + task["subject"])

    update_task_status(task_id, "PROCESSING", note="开始处理")
    out.emit("任务状态：PROCESSING")

    core = task["analysis"]["core"]

    out.emit()
    out.emit("任务内容：")
    out.emit(core)

    # ==============================
    # 第一步：检索个人资料
    # ==============================

    out.emit()
    out.emit("正在检索个人资料...")

    results = search_documents(core)

    out.emit()
    out.emit("找到以下个人资料：")

    for result in results:
        out.emit()
        out.emit("文件：" + result["file"])
        out.emit(result["content"])

    personal_info = _format_personal_info(results)

    # ==============================
    # 第二步：让 AI 判断是否需要个人信息
    # ==============================

    prompt = f"""
你是我的个人助手。

现在有一个待处理任务。

任务内容：
{core}

下面是从我的个人资料库中检索到的信息：

{personal_info}

请先判断这个任务是否需要使用我的个人信息。

如果不需要个人信息，例如：
- 转告通知
- 阅读通知
- 普通提醒
- 查看公开信息

则不要强行寻找个人资料。

如果需要个人信息，例如：
- 填写个人申请
- 填写表单
- 发送个人邮件
- 办理需要本人信息的事务

再分析：
1. 需要哪些个人信息
2. 已经有哪些
3. 还缺哪些

要求：
1. 只能使用提供的个人资料。
2. 不要编造个人信息。
3. 先分析这个任务需要哪些信息。
4. 再判断个人资料库中已经有哪些相关信息。
5. 明确列出还缺少哪些信息。
6. 如果任务本身不需要个人信息，也要明确说明。
7. 每一项个人信息都要说明来自哪个文件。
8. 简洁回答。
9. 宿舍报修、填写表单、提交申请、办理事务等任务，
   必然需要姓名、联系方式、地址等个人信息，
   必须判断为需要个人信息。
10. 如果检索到的资料与任务无关，或者没有检索到任何资料，
    不要因此判断任务不需要个人信息；
    此时应把任务所需的信息列入 missing_info。

必须严格按照下面的 JSON 格式返回：

{{
    "need_personal_info": true,
    "required_info": [
        "需要的信息1",
        "需要的信息2"
    ],
    "available_info": [
        {{
            "info": "已经拥有的信息",
            "source": "来自哪个文件"
        }}
    ],
    "missing_info": [
        "还缺少的信息1",
        "还缺少的信息2"
    ],
    "summary": "对目前信息情况的简要总结"
}}

只返回 JSON，不要添加 Markdown，不要添加解释。
"""

    out.emit()
    out.emit("正在让 AI 分析任务和个人资料的关系...")

    try:
        analysis = ask_llm_json(prompt)
    except ValueError as e:
        out.emit()
        out.emit("AI 返回的不是合法 JSON：")
        out.emit(str(e))

        update_task_status(task_id, "WAITING_USER", note="AI 信息分析失败")
        out.ok = False
        return out

    if "need_personal_info" not in analysis:
        out.emit()
        out.emit("AI 分析结果缺少必要字段。")

        update_task_status(task_id, "WAITING_USER", note="AI 分析结果不完整")
        out.ok = False
        return out

    # ==============================
    # 第三步：显示 AI 分析结果
    # ==============================

    out.emit()
    out.emit("AI 信息分析结果：")

    out.emit()
    out.emit("是否需要个人信息：" + str(analysis["need_personal_info"]))

    out.emit()
    out.emit("完成任务需要的信息：")
    for info in analysis.get("required_info", []):
        out.emit("- " + str(info))

    out.emit()
    out.emit("已经拥有的信息：")
    for info in analysis.get("available_info", []):
        out.emit("- " + str(info["info"]))
        out.emit("  来源：" + str(info["source"]))

    out.emit()
    out.emit("还缺少的信息：")
    for info in analysis.get("missing_info", []):
        out.emit("- " + str(info))

    out.emit()
    out.emit("总结：")
    out.emit(str(analysis.get("summary", "")))

    # ==============================
    # 第四步：普通任务
    # ==============================

    is_repair = task["analysis"].get("type") == "宿舍报修"

    if analysis["need_personal_info"] is False and not is_repair:
        update_task_status(task_id, "COMPLETED", note="无需个人信息，任务完成")

        out.emit()
        out.emit("该任务不需要个人信息。")
        out.emit("任务已经完成。")
        out.emit("任务状态：COMPLETED")

        return out

    # ==============================
    # 第五步：检查是否缺少信息
    # ==============================

    # 注意：宿舍报修任务的完整性由报修表单字段检查把关（第六步），
    # 不依赖这一步对个人信息的判断，避免 AI 误判导致任务提前结束。
    if len(analysis.get("missing_info", [])) > 0 and not is_repair:

        update_task_status(task_id, "WAITING_USER", note="缺少个人信息")

        out.emit()
        out.emit("任务还缺少以下信息：")

        for info in analysis["missing_info"]:
            out.emit("- " + str(info))

        out.emit()
        out.emit("任务状态：WAITING_USER")
        out.emit("等待用户提供信息。")

        return out

    # ==============================
    # 第六步：宿舍报修字段提取
    # ==============================

    if is_repair:

        out.emit()
        out.emit("正在整理宿舍报修表单信息...")

        user_input_text = _format_user_inputs(task.get("user_inputs", []))

        try:
            repair_fields = _extract_repair_fields(
                core,
                user_input_text,
                personal_info
            )
        except ValueError as e:
            out.emit()
            out.emit("AI 返回的宿舍报修字段不是合法 JSON：")
            out.emit(str(e))

            update_task_status(task_id, "WAITING_USER", note="报修字段提取失败")
            out.ok = False
            return out

        repair_data = _build_repair_data(repair_fields)

        update_task_data(task_id, "repair_data", repair_data)

        out.emit()
        out.emit("宿舍报修数据已经生成：")

        for key, value in repair_data.items():
            out.emit(f"{key}: {value}")

        # 检查报修字段是否完整
        if _missing_repair_fields_to_waiting(out, task_id, repair_data):
            return out

    # ==============================
    # 第七步：信息完整，生成确认单等待用户确认
    # ==============================

    return request_confirmation(task_id)


# --------------------------------------------------
# 生成确认单（等待用户确认）
# --------------------------------------------------

def request_confirmation(task_id):
    """生成并保存确认单快照，任务进入 WAITING_CONFIRMATION。

    确认单里包含将要执行的操作、关键字段和可能后果。
    入口层（CLI / Web）必须在询问用户之前展示确认单，
    用户明确同意后才能调用 confirm_task()。
    """

    out = Outcome()

    task = get_task(task_id)

    if task is None:
        out.ok = False
        out.emit("任务不存在。")
        return out

    core = task["analysis"]["core"]

    if task["analysis"].get("type") == "宿舍报修":

        repair_data = task.get("repair_data")

        if not repair_data:
            update_task_status(
                task_id,
                "WAITING_USER",
                note="缺少报修数据，无法生成确认单"
            )
            out.ok = False
            out.emit("缺少宿舍报修数据。")
            return out

        confirmation = {
            "title": "即将提交 EHALL 宿舍报修申请",
            "fields": [
                {"label": label, "value": repair_data.get(key, "")}
                for key, label in REPAIR_CONFIRM_FIELDS
            ],
            "warning": "确认后将提交该 EHALL 报修申请。",
            "created_at": _now(),
        }

    else:

        confirmation = {
            "title": "即将执行任务",
            "fields": [
                {"label": "任务内容", "value": core},
                {
                    "label": "具体操作",
                    "value": str(task["analysis"].get("action") or ""),
                },
            ],
            "warning": "确认后 Agent 将执行该任务，可能产生实际后果。",
            "created_at": _now(),
        }

    # 保存确认单快照，UI 之后只读快照，不受后续修改影响
    update_task_data(task_id, "confirmation", confirmation)
    update_task_status(
        task_id,
        "WAITING_CONFIRMATION",
        note="已生成确认单，等待用户确认"
    )

    out.emit()
    out.emit("个人信息已经足够。")
    out.emit("该任务可能需要进一步操作，因此等待用户确认。")
    out.emit()
    out.emit("================================")
    out.emit(confirmation["title"])
    out.emit("================================")

    for field in confirmation["fields"]:
        out.emit(field["label"] + "：" + str(field["value"]))

    out.emit()
    out.emit("注意：" + confirmation["warning"])
    out.emit("================================")
    out.emit()
    out.emit("任务状态：WAITING_CONFIRMATION")

    return out


# --------------------------------------------------
# 继续处理 WAITING_USER 任务
# --------------------------------------------------

def continue_task(task_id, user_input):
    out = Outcome()

    # 获取任务
    task = get_task(task_id)

    if task is None:
        out.ok = False
        out.emit("任务不存在")
        return out

    # 只有等待用户状态才能继续
    if task["status"] != "WAITING_USER":
        out.ok = False
        out.emit("当前任务不需要用户输入")
        return out

    out.emit("收到用户输入：")
    out.emit(user_input)

    # 保存用户输入
    add_user_input(task_id, user_input)

    out.emit("用户输入已经保存")

    # 重新读取任务
    task = get_task(task_id)

    # 获取所有用户输入
    user_inputs = task.get("user_inputs", [])

    user_input_text = _format_user_inputs(user_inputs)

    # 获取任务内容
    core = task["analysis"]["core"]

    # ==============================
    # 如果是宿舍报修，重新提取报修字段
    # ==============================

    if task["analysis"].get("type") == "宿舍报修":

        out.emit()
        out.emit("正在根据用户补充信息重新整理宿舍报修数据...")

        # 重新检索个人资料，保证资料库更新后也能生效
        results = search_documents(core)
        personal_info = _format_personal_info(results)

        try:
            repair_fields = _extract_repair_fields(
                core,
                user_input_text,
                personal_info
            )
        except ValueError as e:
            out.emit()
            out.emit("AI 返回的宿舍报修字段不是合法 JSON：")
            out.emit(str(e))

            update_task_status(task_id, "WAITING_USER", note="报修字段提取失败")
            out.ok = False
            return out

        # 构造 EHALL 报修数据
        repair_data = _build_repair_data(repair_fields)

        # 保存到任务
        update_task_data(task_id, "repair_data", repair_data)

        out.emit()
        out.emit("宿舍报修数据已经重新生成：")

        for key, value in repair_data.items():
            out.emit(f"{key}: {value}")

        # 检查报修字段是否完整
        if _missing_repair_fields_to_waiting(out, task_id, repair_data):
            return out

    # ==============================
    # 让 AI 判断任务下一步状态
    # ==============================

    prompt = f"""
你是我的个人助手。

现在正在继续处理一个任务。

任务内容：
{core}

用户之前提供的信息：
{user_input_text}

请判断这个任务现在应该进入什么状态。

只能从下面五个状态中选择：

PROCESSING
WAITING_USER
WAITING_CONFIRMATION
EXECUTING
COMPLETED

判断规则：

1. 如果还需要用户提供信息，返回 WAITING_USER。
2. 如果信息已经足够，但执行操作前必须得到用户明确确认，返回 WAITING_CONFIRMATION。
3. 如果已经获得用户信息，但 Agent 还需要继续执行普通操作，返回 PROCESSING。
4. 如果用户已经明确确认，可以进入 EXECUTING。
5. 如果任务已经完成，返回 COMPLETED。
6. 对可能产生实际后果的操作，不得自行确认。
7. 不要自行执行任何操作。
8. 不要编造用户没有提供的信息。

特别注意：

如果下一步涉及以下操作：

- 提交表单
- 退课
- 取消申请
- 发送邮件
- 删除数据
- 其他可能产生实际后果的操作

即使信息已经完整，也必须返回 WAITING_CONFIRMATION，
不能直接返回 EXECUTING 或 COMPLETED。

如果需要用户继续提供信息，请生成一个明确的问题。

必须严格返回下面的 JSON：

{{
    "next_status": "PROCESSING/WAITING_USER/WAITING_CONFIRMATION/EXECUTING/COMPLETED",
    "need_user_input": true,
    "question": "需要用户回答的问题，没有则为 null",
    "reason": "为什么进入这个状态"
}}

只返回 JSON，不要添加 Markdown，不要添加解释。
"""

    out.emit()
    out.emit("正在让 AI 判断任务下一步状态...")

    try:
        decision = ask_llm_json(prompt)
    except ValueError as e:
        out.emit()
        out.emit("AI 返回的不是合法 JSON：")
        out.emit(str(e))

        update_task_status(task_id, "WAITING_USER", note="AI 状态判断失败")
        out.ok = False
        return out

    out.emit()
    out.emit("AI 状态判断：")
    out.emit("下一状态：" + str(decision.get("next_status")))
    out.emit("是否需要用户输入：" + str(decision.get("need_user_input")))
    out.emit("问题：" + str(decision.get("question")))
    out.emit("原因：" + str(decision.get("reason")))

    # 根据 AI 判断修改任务状态
    next_status = decision.get("next_status", "WAITING_USER")

    # 需要确认时，生成确认单快照（先展示，再等用户确认）
    if next_status == "WAITING_CONFIRMATION":
        return request_confirmation(task_id)

    update_task_status(task_id, next_status, note="AI 判断下一步状态")

    out.emit()
    out.emit("任务状态已经更新为：" + str(next_status))

    return out


# --------------------------------------------------
# 执行 WAITING_CONFIRMATION 任务
# --------------------------------------------------

def confirm_task(task_id):
    """执行已经过用户明确确认的任务。

    注意：本函数只负责执行，不负责展示。
    确认单的展示由 request_confirmation() 生成并交给入口层完成；
    只有用户在 CLI / Web 上看到确认单并明确同意后，
    入口层才允许调用本函数。Agent 自身永远不会代替用户确认。
    """

    out = Outcome()

    task = get_task(task_id)

    if not task:
        out.ok = False
        out.emit("任务不存在")
        return out

    if task["status"] != "WAITING_CONFIRMATION":
        out.ok = False
        out.emit("当前任务不需要确认")
        return out

    # ==============================
    # EHALL 宿舍报修
    # ==============================

    if task["analysis"].get("type") == "宿舍报修":

        repair_data = task.get("repair_data")

        if not repair_data:
            update_task_status(task_id, "WAITING_USER", note="缺少宿舍报修数据")
            out.ok = False
            out.emit("缺少宿舍报修数据")
            return out

        update_task_status(task_id, "EXECUTING", note="用户已确认，开始执行")
        out.emit("任务状态：EXECUTING")

        # ==============================
        # EHALL 提交
        # ==============================

        from tools.ehall import submit_repair

        result = submit_repair(repair_data)

        update_task_data(task_id, "result", {
            "at": _now(),
            "success": result.get("success", False),
            "message": result.get("message", ""),
        })

        if result.get("success"):
            update_task_status(task_id, "COMPLETED", note="提交成功")
            out.emit(result.get("message", "提交成功"))
            out.data["result"] = result
            return out

        # 提交失败：进入 FAILED 终态，不再卡在 EXECUTING
        update_task_status(task_id, "FAILED", note="EHALL 提交失败")

        out.ok = False
        out.emit(result.get("message", "提交失败"))
        out.emit("任务状态：FAILED")
        out.data["result"] = result
        return out

    # ==============================
    # 其他任务暂时保持模拟执行
    # ==============================

    update_task_status(task_id, "EXECUTING", note="用户已确认，开始执行")
    update_task_data(task_id, "result", {
        "at": _now(),
        "success": True,
        "message": "模拟执行完成",
    })
    update_task_status(task_id, "COMPLETED", note="模拟执行完成")

    out.emit("任务执行完成")

    return out


def cancel_task(task_id):
    """用户明确取消任务。"""

    out = Outcome()

    task = get_task(task_id)

    if task is None:
        out.ok = False
        out.emit("任务不存在")
        return out

    if task["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        out.ok = False
        out.emit("当前任务不需要取消")
        return out

    update_task_data(task_id, "result", {
        "at": _now(),
        "success": False,
        "message": "用户取消任务",
    })
    update_task_status(task_id, "CANCELLED", note="用户取消任务")

    out.emit("任务已经取消。")
    out.emit("任务状态：CANCELLED")

    return out

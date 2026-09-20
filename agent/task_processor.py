from tools.personal_db import search_documents
from agent.llm import ask_llm_json
from agent.task_manager import (
    get_task,
    update_task_status,
    add_user_input,
    update_task_data
)


def process_task(task_id):
    task = get_task(task_id)

    if task is None:
        print("任务不存在。")
        return

    print("开始处理任务：", task["subject"])

    update_task_status(task_id, "PROCESSING")
    print("任务状态：PROCESSING")

    core = task["analysis"]["core"]

    print()
    print("任务内容：")
    print(core)

    # ==============================
    # 第一步：检索个人资料
    # ==============================

    print()
    print("正在检索个人资料...")

    results = search_documents(core)

    print()
    print("找到以下个人资料：")

    personal_info = ""

    for result in results:
        print()
        print("文件：", result["file"])
        print(result["content"])

        personal_info += (
            "\n文件：" + result["file"] +
            "\n内容：\n" + result["content"] +
            "\n"
        )

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

    print()
    print("正在让 AI 分析任务和个人资料的关系...")

    try:
        analysis = ask_llm_json(prompt)
    except ValueError as e:
        print()
        print("AI 返回的不是合法 JSON：")
        print(e)

        update_task_status(task_id, "WAITING_USER")
        return

    # ==============================
    # 第三步：显示 AI 分析结果
    # ==============================

    print()
    print("AI 信息分析结果：")

    print()
    print("是否需要个人信息：", analysis["need_personal_info"])

    print()
    print("完成任务需要的信息：")
    for info in analysis["required_info"]:
        print("-", info)

    print()
    print("已经拥有的信息：")
    for info in analysis["available_info"]:
        print("-", info["info"])
        print("  来源：", info["source"])

    print()
    print("还缺少的信息：")
    for info in analysis["missing_info"]:
        print("-", info)

    print()
    print("总结：")
    print(analysis["summary"])

    # ==============================
    # 第四步：普通任务
    # ==============================

    if analysis["need_personal_info"] is False:
        update_task_status(task_id, "COMPLETED")

        print()
        print("该任务不需要个人信息。")
        print("任务已经完成。")
        print("任务状态：COMPLETED")

        return

    # ==============================
    # 第五步：检查是否缺少信息
    # ==============================

    if len(analysis["missing_info"]) > 0:

        update_task_status(task_id, "WAITING_USER")

        print()
        print("任务还缺少以下信息：")

        for info in analysis["missing_info"]:
            print("-", info)

        print()
        print("任务状态：WAITING_USER")
        print("等待用户提供信息。")

        return

    # ==============================
    # 第六步：宿舍报修字段提取
    # ==============================

    if task["analysis"].get("type") == "宿舍报修":

        print()
        print("正在整理宿舍报修表单信息...")

        user_inputs = task.get("user_inputs", [])

        user_input_text = ""

        for i, user_input in enumerate(user_inputs):
            user_input_text += f"{i + 1}. {user_input}\n"

        repair_prompt = f"""
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

        try:
            repair_fields = ask_llm_json(repair_prompt)
        except ValueError as e:
            print()
            print("AI 返回的宿舍报修字段不是合法 JSON：")
            print(e)

            update_task_status(task_id, "WAITING_USER")
            return

        # ==============================
        # 保存宿舍报修数据
        # ==============================

        from tools.ehall import build_repair_data

        repair_data = build_repair_data(
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

        update_task_data(
            task_id,
            "repair_data",
            repair_data
        )

        print()
        print("宿舍报修数据已经生成：")

        for key, value in repair_data.items():
            print(f"{key}: {value}")

        # ==============================
        # 检查报修字段是否完整
        # ==============================

        required_repair_fields = {
            "SJH": "手机号",
            "XMDM": "报修类型",
            "QYDM": "报修区域",
            "GZDD": "详细地点",
            "DZ_FBSMKSSJ": "上门服务开始时间",
            "DZ_FBSMJSSJ": "上门服务结束时间",
            "GZMS": "问题描述"
        }

        missing_repair_fields = []

        for key, name in required_repair_fields.items():
            if not repair_data.get(key):
                missing_repair_fields.append(name)

        if len(missing_repair_fields) > 0:

            update_task_status(task_id, "WAITING_USER")

            print()
            print("宿舍报修还缺少以下信息：")

            for field in missing_repair_fields:
                print("-", field)

            print()
            print("任务状态：WAITING_USER")

            return

    # ==============================
    # 第七步：信息完整，等待确认
    # ==============================

    update_task_status(task_id, "WAITING_CONFIRMATION")

    print()
    print("个人信息已经足够。")
    print("该任务可能需要进一步操作，因此等待用户确认。")
    print("任务状态：WAITING_CONFIRMATION")


def continue_task(task_id, user_input):

    # 获取任务
    task = get_task(task_id)

    if task is None:
        print("任务不存在")
        return

    # 只有等待用户状态才能继续
    if task["status"] != "WAITING_USER":
        print("当前任务不需要用户输入")
        return

    print("收到用户输入：")
    print(user_input)

    # 保存用户输入
    add_user_input(task_id, user_input)

    print("用户输入已经保存")

    # 重新读取任务
    task = get_task(task_id)

    # 获取所有用户输入
    user_inputs = task.get("user_inputs", [])

    user_input_text = ""

    for i in range(len(user_inputs)):
        user_input_text += str(i + 1) + ". "
        user_input_text += user_inputs[i]
        user_input_text += "\n"

    # 获取任务内容
    core = task["analysis"]["core"]

    # ==============================
    # 如果是宿舍报修，重新提取报修字段
    # ==============================

    if task["analysis"].get("type") == "宿舍报修":

        print()
        print("正在根据用户补充信息重新整理宿舍报修数据...")

        repair_prompt = f"""
你是我的个人助手。

现在需要准备一份南京大学 EHALL 宿舍报修申请。

任务内容：
{core}

用户已经提供的信息：
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

1. 只能使用任务内容和用户提供的信息。
2. 不允许编造任何字段。
3. 无法确定的字段必须返回空字符串。
4. 时间必须转换成 yyyy-MM-dd HH:mm。
5. 用户没有提供具体时间，不要自行猜测。
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

        print()
        print("正在让 AI 提取宿舍报修字段...")

        try:
            repair_fields = ask_llm_json(repair_prompt)
        except ValueError as e:
            print()
            print("AI 返回的宿舍报修字段不是合法 JSON：")
            print(e)

            update_task_status(task_id, "WAITING_USER")
            return

        # 构造 EHALL 报修数据
        from tools.ehall import build_repair_data

        repair_data = build_repair_data(
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

        # 保存到任务
        update_task_data(
            task_id,
            "repair_data",
            repair_data
        )

        print()
        print("宿舍报修数据已经重新生成：")

        for key, value in repair_data.items():
            print(f"{key}: {value}")

        # ==============================
        # 检查报修字段是否完整
        # ==============================

        required_repair_fields = {
            "SJH": "手机号",
            "XMDM": "报修类型",
            "QYDM": "报修区域",
            "GZDD": "详细地点",
            "DZ_FBSMKSSJ": "上门服务开始时间",
            "DZ_FBSMJSSJ": "上门服务结束时间",
            "GZMS": "问题描述"
        }

        missing_repair_fields = []

        for key, name in required_repair_fields.items():
            if not repair_data.get(key):
                missing_repair_fields.append(name)

        if len(missing_repair_fields) > 0:

            update_task_status(task_id, "WAITING_USER")

            print()
            print("宿舍报修还缺少以下信息：")

            for field in missing_repair_fields:
                print("-", field)

            print()
            print("任务状态：WAITING_USER")

            return

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

    print()
    print("正在让 AI 判断任务下一步状态...")

    try:
        decision = ask_llm_json(prompt)
    except ValueError as e:
        print()
        print("AI 返回的不是合法 JSON：")
        print(e)

        update_task_status(task_id, "WAITING_USER")
        return

    print()
    print("AI 状态判断：")
    print("下一状态：", decision["next_status"])
    print("是否需要用户输入：", decision["need_user_input"])
    print("问题：", decision["question"])
    print("原因：", decision["reason"])

    # 根据 AI 判断修改任务状态
    update_task_status(
        task_id,
        decision["next_status"]
    )

    print()
    print("任务状态已经更新为：", decision["next_status"])

def confirm_task(task_id):
    """用户确认后执行任务"""

    task = get_task(task_id)

    if not task:
        return False, "任务不存在"

    if task["status"] != "WAITING_CONFIRMATION":
        return False, "当前任务不需要确认"

    # ==============================
    # EHALL 宿舍报修
    # ==============================

    if task["analysis"].get("type") == "宿舍报修":

        repair_data = task.get("repair_data")

        if not repair_data:
            update_task_status(task_id, "WAITING_USER")
            return False, "缺少宿舍报修数据"

        # ==============================
        # 提交前展示关键字段
        # ==============================

        print()
        print("================================")
        print("即将提交 EHALL 宿舍报修申请")
        print("================================")

        print("手机号：", repair_data.get("SJH", ""))
        print("报修类型：", repair_data.get("XMDM", ""))
        print("报修区域：", repair_data.get("QYDM", ""))
        print("详细地点：", repair_data.get("GZDD", ""))
        print("上门服务开始时间：", repair_data.get("DZ_FBSMKSSJ", ""))
        print("上门服务结束时间：", repair_data.get("DZ_FBSMJSSJ", ""))
        print("问题描述：", repair_data.get("GZMS", ""))
        print("备注：", repair_data.get("BZ", ""))

        print()
        print("注意：确认后将提交该 EHALL 报修申请。")
        print("================================")

        # 用户已经在上层流程明确确认
        update_task_status(task_id, "EXECUTING")

        # ==============================
        # EHALL 提交
        # ==============================

        from tools.ehall import submit_repair

        result = submit_repair(repair_data)

        if result.get("success"):
            update_task_status(task_id, "COMPLETED")
            return True, result.get("message", "提交成功")

        # 当前 EHALL 工具还没有真实提交能力
        update_task_status(task_id, "EXECUTING")

        return False, result.get("message", "提交失败")

    # ==============================
    # 其他任务暂时保持模拟执行
    # ==============================

    update_task_status(task_id, "COMPLETED")

    return True, "任务执行完成"
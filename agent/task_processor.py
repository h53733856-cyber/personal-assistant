import json
from tools.personal_db import search_documents
from agent.llm import ask_llm
from agent.task_manager import (
    get_task,
    update_task_status,
    add_user_input
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

    response = ask_llm(prompt)

    try:
        analysis = json.loads(response)
    except json.JSONDecodeError:
        print()
        print("AI 返回的不是合法 JSON：")
        print(response)

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
    # 第四步：根据分析结果决定任务状态
    # ==============================

    if analysis["need_personal_info"] is False:
        # 普通通知，不需要用户提供任何个人信息
        update_task_status(task_id, "COMPLETED")

        print()
        print("该任务不需要个人信息。")
        print("任务已经完成。")
        print("任务状态：COMPLETED")

        return

    # 如果需要个人信息，但是还有信息缺失
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

    # 需要个人信息，并且信息已经足够
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

    prompt = f"""
    你是我的个人助手。

    现在正在继续处理一个任务。

    任务内容：
    {core}

    用户之前提供的信息：
    {user_input_text}

    请判断这个任务现在应该进入什么状态。

    只能从下面三个状态中选择：

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
        "next_status": "PROCESSING/WAITING_USER/COMPLETED",
        "need_user_input": true,
        "question": "需要用户回答的问题，没有则为 null",
        "reason": "为什么进入这个状态"
    }}

    只返回 JSON，不要添加 Markdown，不要添加解释。
    """

    print()
    print("正在让 AI 判断任务下一步状态...")

    result = ask_llm(prompt)

    # 把 AI 返回的 JSON 转成 Python 字典
    result = result.strip()
    decision = json.loads(result)

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

    # 获取任务
    task = get_task(task_id)

    if task is None:
        print("任务不存在")
        return

    # 只有 WAITING_CONFIRMATION 才能确认
    if task["status"] != "WAITING_CONFIRMATION":
        print("当前任务不需要确认")
        return

    print("用户已明确确认任务。")

    # 进入执行状态
    update_task_status(task_id, "EXECUTING")

    print("任务状态：EXECUTING")

    # 这里暂时模拟真正的执行操作
    print("正在执行任务...")

    # 模拟执行成功
    update_task_status(task_id, "COMPLETED")

    print("任务执行完成。")
    print("任务状态：COMPLETED")
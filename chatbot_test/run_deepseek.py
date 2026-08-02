"""
Interactive CLI chat with DeepSeek V4 Pro via Ark (Volcengine) API.
Continuous conversation + function calling to inject knowledge base files.
"""
import requests
import json
import sys
import os

# ============================================================
# Configuration
# ============================================================
URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
HEADERS = {
    "Authorization": "Bearer 9b6f70ec-40a3-4bfb-abd7-9da6178867a0",
    "Content-Type": "application/json",
}
MODEL = "deepseek-v4-pro-260425"

# Set your system prompt here
SYSTEM_PROMPT = [
    "你是一个专业的学术任务拆解与时间规划 Agent。"
    "你的核心工作是将用户的长程任务拆分为具体的子任务，并设置合理的 Deadline。"
    "【工作流程要求】："
    "1. 识别任务：判断用户的任务是否涉及特定学科（如物理IA、历史论文）。"
    "2. 调用工具：如果是特定学科，你 **必须** 调用 `get_subject_guidelines` 工具获取该学科的专属指南。"
    "3. 遵循指南："
       "- 工具返回的指南包含了该学科专用的拆解步骤、防坑建议和时间分配比例。"
       "- 你的输出 **必须绝对服从** 指南中的步骤和建议，不能遗漏指南中要求必须包含的环节（如：物理必须有误差分析）。"
    "4. 个性化排期：根据用户提供的截止日期（Deadline）和指南中的时间分配比例，为每个子任务推算具体的日期。并在每个子任务后附上指南中的“注意事项/防坑指南”。"
]

# Where to find .md knowledge base files (relative to this script)
KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")

# ============================================================
# Function / Tool Definitions
# ============================================================
TOOLS = [
    {
        "type": "function",
        "name": "get_subject_guidelines",
        "description": (
            "当用户要求拆解特定学科的长程任务（如 IB IA、EE、AP 论文、毕业论文等）时，"
            "必须调用此工具获取该学科的具体拆解指南、评分标准和时间规划建议。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subject_task_type": {
                    "type": "string",
                    "description": (
                        "任务的学科和类型，例如 'IB_Physics_IA', "
                        "'IB_Chemistry_IA', 'AP_History_Essay' 等。"
                    ),
                    "enum": [
                        "IB_Physics_IA",
                        "IB_Chemistry_IA",
                        "AP_History_Essay",
                        "General_Thesis",
                    ],
                }
            },
            "required": ["subject_task_type"],
        },
    }
]


# ============================================================
# Knowledge Base Access
# ============================================================
def read_knowledge_base(subject_task_type: str) -> str:
    """去 knowledge_base 文件夹读取对应名称的 .md 文件，返回全文。
    例如 subject_task_type='IB_Physics_IA' → 读取 IB_Physics_IA.md"""
    filepath = os.path.join(KNOWLEDGE_BASE_DIR, f"{subject_task_type}.md")

    if not os.path.exists(filepath):
        # 列出已有的文件，提示用户
        existing = (
            ", ".join(f.replace(".md", "") for f in os.listdir(KNOWLEDGE_BASE_DIR))
            if os.path.isdir(KNOWLEDGE_BASE_DIR)
            else "(知识库文件夹不存在)"
        )
        return (
            f"[知识库错误] 未找到 '{subject_task_type}' 的指南文件。\n"
            f"当前可用的指南: {existing}\n"
            f"请检查 knowledge_base/ 文件夹或更新 file mapping。"
        )

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# Core API Call — handles both text and function_call responses
# ============================================================
def call_api(conversation, with_tools=True):
    """
    把 conversation 发给 API，解析流式响应。

    参数:
      with_tools: 是否携带 tools 定义。首次发送要带（让 AI 决定调用哪些函数），
                  函数执行完后的重调用不带（避免 AI 重复调用同一函数）。

    返回值可能的情况：
      - {"type": "text",      "content": "AI 的回复文本"}
      - {"type": "function_call", "call_id": "...", "name": "...", "arguments": {...} }
      - {"type": "error",     "message": "错误描述"}
      - {"type": "empty"}                                    ← 没有任何输出项（罕见）
    """
    payload = {
        "model": MODEL,
        "stream": True,
        "input": conversation,
    }
    # 只在需要时带 tools，避免模型在拿到知识库后重复调用同一函数
    if with_tools:
        payload["tools"] = TOOLS

    resp = requests.post(URL, headers=HEADERS, json=payload, stream=True)
    if resp.status_code != 200:
        print(f"\n[HTTP {resp.status_code}] {resp.text}", file=sys.stderr)
        return {"type": "error", "message": resp.text}

    # ---------- 流式解析状态 ----------
    current_event = None

    # 当前正在处理的输出项
    cur_item_type = None   # "function_call" | "message"
    cur_item_data = {}     # 存放累积的参数 / 文本

    # 已完成的输出项列表
    output_items = []

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")

        # --- 记住事件类型 ---
        if line.startswith("event: "):
            current_event = line[7:].strip()

        # --- 处理数据行 ---
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            # ---- 一个新的输出项开始了 ----
            if current_event == "response.output_item.added":
                item = data.get("item", {})
                item_type = item.get("type", "")

                if item_type == "function_call":
                    cur_item_type = "function_call"
                    cur_item_data = {
                        "call_id": item.get("call_id", ""),
                        "name": item.get("name", ""),
                        "arguments": "",
                    }
                elif item_type == "message":
                    cur_item_type = "message"
                    cur_item_data = {"content": ""}

            # ---- 函数调用的参数片段（逐 delta 累积） ----
            elif current_event == "response.function_call_arguments.delta":
                if cur_item_type == "function_call":
                    cur_item_data["arguments"] += data.get("delta", "")

            # ---- AI 的文字片段（逐 delta 累积并实时打印） ----
            elif current_event == "response.output_text.delta":
                if cur_item_type == "message":
                    delta = data.get("delta", "")
                    cur_item_data["content"] += delta
                    print(delta, end="", flush=True)

            # ---- 当前输出项结束 ----
            elif current_event == "response.output_item.done":
                if cur_item_type == "function_call":
                    output_items.append({
                        "type": "function_call",
                        "call_id": cur_item_data["call_id"],
                        "name": cur_item_data["name"],
                        # 把累积的 JSON 字符串解析成 dict
                        "arguments": json.loads(cur_item_data["arguments"]),
                    })
                elif cur_item_type == "message":
                    output_items.append({
                        "type": "text",
                        "content": cur_item_data["content"],
                    })
                cur_item_type = None
                cur_item_data = {}

            # ---- 整个响应结束（兜底：把还未 done 的项也收进去） ----
            elif current_event == "response.completed":
                if cur_item_type == "function_call" and cur_item_data.get("arguments"):
                    output_items.append({
                        "type": "function_call",
                        "call_id": cur_item_data["call_id"],
                        "name": cur_item_data["name"],
                        "arguments": json.loads(cur_item_data["arguments"]),
                    })
                elif cur_item_type == "message" and cur_item_data.get("content"):
                    output_items.append({
                        "type": "text",
                        "content": cur_item_data["content"],
                    })
                break

    # ---------- 决定返回什么 ----------
    if not output_items:
        return {"type": "empty"}

    # 如果本次响应里有 function_call，优先返回 function_call
    # （让调用方先执行函数、注入结果、再重新请求 AI）
    for item in output_items:
        if item["type"] == "function_call":
            return item

    # 否则把所有的 text 项拼接成一段完整回复
    full_text = "".join(
        item["content"] for item in output_items if item["type"] == "text"
    )
    return {"type": "text", "content": full_text}


# ============================================================
# Executes a function call and injects the result into context
# ============================================================
def execute_and_inject(conversation, func_call):
    """
    根据 func_call 里的 name / arguments，实际执行函数，
    然后把知识库内容作为上下文注入 conversation（Ark API 不支持
    function_call / tool 这类 content type，所以直接用 role 注入）。
    """
    name = func_call["name"]
    args = func_call.get("arguments", {})
    call_id = func_call.get("call_id", "")

    if name == "get_subject_guidelines":
        subject = args.get("subject_task_type", "")
        print(f"\n  [🔍 正在查阅知识库: {subject}]")
        kb_content = read_knowledge_base(subject)
        print(f"  [✅ 已加载 {subject}.md ({len(kb_content)} 字符)]")

        # ---- 把知识库内容作为上下文注入 ----
        # Ark API 不支持 function_call / tool 这两种 content type，
        # 所以这里用两种消息把上下文塞进去：
        #   1. 一条 assistant 消息，记录 AI 决定查找了哪个知识库
        #   2. 一条 system 消息，把知识库全文作为参考材料注入
        conversation.append({
            "role": "assistant",
            "content": make_text_block(
                f"我需要查阅 {subject} 的详细指南来回答这个问题。"
            ),
        })
        conversation.append({
            "role": "system",
            "content": make_text_block(
                f"【知识库内容：{subject}】\n\n{kb_content}"
            ),
        })

    else:
        # 未知函数——记录警告
        conversation.append({
            "role": "system",
            "content": make_text_block(
                f"[系统提示] 调用了未知函数: {name}，参数: {json.dumps(args, ensure_ascii=False)}"
            ),
        })


# ============================================================
# Makes a text block the way the API expects
# ============================================================
def make_text_block(text):
    return [{"type": "input_text", "text": text}]


# ============================================================
# Helpers
# ============================================================
def make_text_block(text):
    return [{"type": "input_text", "text": text}]


# ============================================================
# Main Chat Loop
# ============================================================
def chat_loop():
    conversation = [
        {"role": "system", "content": make_text_block(SYSTEM_PROMPT)},
    ]

    print("=" * 55)
    print(f"  Model : {MODEL}")
    print(f"  System: {SYSTEM_PROMPT}")
    print(f"  Tools : {', '.join(t['name'] for t in TOOLS)}")
    print("=" * 55)
    print("Type 'exit' or 'quit' to end. Type 'clear' to reset context.")
    print()

    while True:
        # --- 读取用户输入 ---
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        if user_input.lower() == "clear":
            conversation = [
                {"role": "system", "content": make_text_block(SYSTEM_PROMPT)},
            ]
            print("[Context cleared]\n")
            continue

        # --- 追加用户消息 ---
        conversation.append({
            "role": "user",
            "content": make_text_block(user_input),
        })

        # --- Agent 循环：发送 → 检测 function_call → 执行 → 再发送 ---
        # 这个循环最多跑 3 轮，防止死循环（模型理论上不会无限调用函数）
        MAX_FUNCTION_ROUNDS = 3
        has_tools = True  # 第一轮带 tools
        for _ in range(MAX_FUNCTION_ROUNDS):
            print("AI  > ", end="", flush=True)
            result = call_api(conversation, with_tools=has_tools)
            print()  # 换行

            # ---- 情况 1: 正常文本回复 ----
            if result["type"] == "text":
                conversation.append({
                    "role": "assistant",
                    "content": make_text_block(result["content"]),
                })
                break

            # ---- 情况 2: AI 请求调用函数 ----
            elif result["type"] == "function_call":
                execute_and_inject(conversation, result)
                has_tools = False  # 知识已注入，后续调用不再带 tools，避免重复调用
                # 不 break，继续循环让 AI 基于知识库内容生成回复

            # ---- 情况 3: 空响应 / 错误 ----
            elif result["type"] == "error":
                print(f"  [API 错误] {result['message']}")
                conversation.pop()  # 移除出错的用户消息
                break

            elif result["type"] == "empty":
                print("  [空响应] AI 没有返回任何内容")
                break
        else:
            # for 循环正常结束 = 函数调用轮次用完了还没拿到文本回复
            print("  [警告] 函数调用轮次已达上限，但未获得最终回复。")

        print()  # 回合之间空行


# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chat_loop()

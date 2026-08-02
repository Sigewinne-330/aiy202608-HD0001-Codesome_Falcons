"""
Interactive CLI chat with DeepSeek V4 Pro via Ark (Volcengine) API.
Continuous conversation with context maintained across turns.
"""
import requests
import json
import sys

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
SYSTEM_PROMPT = "你是一个IB课程规划导师"


# ============================================================
# SSE Streaming Parser
# ============================================================
def stream_response(conversation):
    """把到目前为止的全部对话历史发给 AI，然后逐字流式打印 AI 的回复。
    conversation 是一个列表，里面按时间顺序存放了 system/user/assistant 消息。
    返回值是 AI 回复的完整文本（用于追加到对话历史中）。"""

    # ================================================================
    # 第 1 步：打包请求数据（payload）
    # ================================================================
    # 这三样东西是 API 必须要的：
    #   - "model"：告诉火山引擎我们要用哪个 AI 模型
    #   - "stream": True：告诉 API "请一边生成一边发给我，不要等全部写完再一次性返回"
    #   - "input"：把当前全部对话历史传进去，这样 AI 才知道之前聊了什么
    payload = {
        "model": MODEL,
        "stream": True,
        "input": conversation,
    }

    # ================================================================
    # 第 2 步：发送 HTTP 请求
    # ================================================================
    # requests.post() 向 API 地址发送一个 POST 请求
    #   - url=URL           → 目标地址（火山引擎的服务器）
    #   - headers=HEADERS   → 请求头，包含授权 token 和数据格式声明
    #   - json=payload      → 自动把 payload 转成 JSON 格式放进请求体
    #   - stream=True       → 告诉 requests 库"不要一次性下载完，保持连接慢慢收数据"
    #                         这和 payload 里的 "stream": True 是对应的：
    #                         payload 里的是告诉 API 流式生成，
    #                         stream=True 是告诉 requests 库要流式接收
    resp = requests.post(URL, headers=HEADERS, json=payload, stream=True)

    # ================================================================
    # 第 3 步：检查请求是否成功
    # ================================================================
    # HTTP 状态码 200 表示"一切正常"，其他都算出错
    #   比如 401 = 鉴权失败（token 过期或填错了）
    #   比如 429 = 请求太频繁被限流了
    #   比如 500 = 服务器内部炸了
    if resp.status_code != 200:
        print(f"\n[HTTP {resp.status_code}] {resp.text}", file=sys.stderr)
        return None  # 返回 None 表示这次调用失败了

    # ================================================================
    # 第 4 步：准备接收流式数据
    # ================================================================
    # SSE（Server-Sent Events）是一种流式协议的格式。
    # API 返回的数据长这样：
    #
    #   event: response.output_text.delta
    #   data: {"delta":"你","...":"..."}
    #
    #   event: response.output_text.delta
    #   data: {"delta":"好","...":"..."}
    #
    #   event: response.completed
    #   data: {...}
    #
    # 每一"块"由两行组成：
    #   - event: 行 → 说明这块数据是什么类型
    #   - data:  行 → 实际内容（JSON 格式）
    # 空行用来分隔不同的事件块。
    #
    # current_event 用来"记住"当前正在处理哪种事件类型
    # output_text   用来累积收集 AI 的完整回复
    current_event = None
    output_text = ""

    # ================================================================
    # 第 5 步：逐行读取 API 返回的数据流
    # ================================================================
    # resp.iter_lines() 是一个迭代器，每次给你"一行"原始字节数据
    # 当 API 还在生成内容时，这里会一直等待新行到达，像一个水龙头慢慢滴水
    for line in resp.iter_lines():

        # --- 5a. 跳过空行 ---
        # SSE 协议用空行分隔事件块，空行本身没有有用信息，直接跳过
        if not line:
            continue

        # --- 5b. 把原始字节解码成 UTF-8 文本 ---
        # 网络传输的都是字节（bytes），而 Python 处理字符串需要 str 类型
        # .decode("utf-8") 就是"请把这些字节按照 UTF-8 编码规则翻译成文字"
        # 为什么必须是 UTF-8？因为 API 返回的中文就是用 UTF-8 编码的，
        # 如果用错编码（比如 GBK、latin-1），中文就会变成乱码
        line = line.decode("utf-8")

        # --- 5c. 处理 "event:" 行 ---
        # 这类行告诉我们接下来那行 data 是什么类型，比如：
        #   response.output_text.delta → 这是 AI 回复的一小段文字
        #   response.completed         → 表示 AI 已经说完了
        # 我们把它记在 current_event 里，等下一行 data 到了再根据类型处理
        if line.startswith("event: "):
            current_event = line[7:].strip()  # 去掉开头的 "event: " 前缀，7 个字符

        # --- 5d. 处理 "data:" 行 ---
        elif line.startswith("data: "):
            # 先提取 "data: " 后面的 JSON 字符串（去掉前 6 个字符，即 "data: "）
            data_str = line[6:]

            # JSON 字符串是无法直接用的，需要 json.loads() 解析成 Python 字典（dict）
            # 比如 '{"delta":"你好"}' 会变成 {"delta": "你好"}，
            # 然后就可以用 data["delta"] 或 data.get("delta") 来取值了
            # 如果 JSON 格式有损坏，json.JSONDecodeError 会被捕获并跳过，防止程序崩溃
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # --- 5d-i. 收到 AI 的文字片段 ---
            # current_event 是 "response.output_text.delta" 说明这一块是
            # AI 刚刚生成的新文字（delta 就是"增量"的意思）
            if current_event == "response.output_text.delta":
                # 从 JSON 里取出 "delta" 字段，就是 AI 刚写出来的几个字
                # data.get("delta", "")：如果 "delta" 字段不存在就返回空字符串，防止报错
                delta = data.get("delta", "")

                # 把这个片段拼接到完整回复里（最后要返回它）
                output_text += delta

                # 立刻打印到屏幕上
                #   print(delta, end="")
                #   - delta 是要打印的内容
                #   - end=""   表示打印后不要自动换行（默认会换行，这里我们要逐字拼接）
                #   - flush=True 表示立刻把缓冲区的内容显示出来，不要等积攒一批再显示
                print(delta, end="", flush=True)

            # --- 5d-ii. AI 说完了 ---
            # current_event 是 "response.completed" 说明流式输出到此结束
            elif current_event == "response.completed":
                break  # 跳出 for 循环，不再继续读数据

    # ================================================================
    # 第 6 步：返回 AI 的完整回复
    # ================================================================
    # 返回的 output_text 会被调用方追加到对话历史里（conversation 列表），
    # 这样下一轮对话时 AI 就知道自己刚才说了什么
    return output_text


# ============================================================
# Conversation helpers
# ============================================================
def make_text_block(text):
    """Wrap a plain string into the content-block format the API expects."""
    return [{"type": "input_text", "text": text}]


def chat_loop():
    # Initialize conversation with system prompt only
    conversation = [
        {"role": "system", "content": make_text_block(SYSTEM_PROMPT)},
    ]

    print("=" * 55)
    print(f"  Model : {MODEL}")
    print(f"  System: {SYSTEM_PROMPT}")
    print("=" * 55)
    print("Type 'exit' or 'quit' to end. Type 'clear' to reset context.")
    print()

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # --- Handle special commands ---
        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        if user_input.lower() == "clear":
            conversation = [
                {"role": "system", "content": make_text_block(SYSTEM_PROMPT)},
            ]
            print("[Context cleared]\n")
            continue

        # --- Append user message & send ---
        conversation.append(
            {"role": "user", "content": make_text_block(user_input)}
        )

        print("AI  > ", end="", flush=True)
        reply = stream_response(conversation)
        print()  # newline after streaming output

        if reply is None:
            # API error — remove the user message that caused it
            conversation.pop()
            continue

        # --- Append assistant reply to context ---
        conversation.append(
            {"role": "assistant", "content": make_text_block(reply)}
        )
        # Print blank line between turns for readability
        print()


# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chat_loop()

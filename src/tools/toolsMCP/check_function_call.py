# LLMモジュールがFunction Callingに対応しているかを確認するためのサンプルコード。
# これによってgemma4がFunction Callingに対応していることを確認した。

import ollama

tools = [{
    "type": "function",
    "function": {
        "name": "get_temperature",
        "description": "室内の温度センサから現在の温度(摂氏)を取得する",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}]

response = ollama.chat(
    model="gemma4:e4b",
    messages=[{"role": "user", "content": "今の室温を教えてください"}],
    tools=tools,
    think=False,
)

message = response["message"]
print("content:", message.get("content"))
print("tool_calls:", message.get("tool_calls"))
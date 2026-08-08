"""
Real Junk (RJ) - MCP Client + ローカルLLMエージェント
-------------------------------------------------
MCPSserver.py をサブプロセスとして起動し、標準入出力(stdio)経由でMCP接続する。
サーバーが公開する get_temperature / set_led のツール一覧を実行時に取得し、
それをOllamaのtools形式に変換してから、LLMが自律的に
「まず温度を確認し、その結果を踏まえてLEDを切り替える」手順を組み立てるのに任せる。

これまでとの一番の違い:
    以前は run_agent_step() の中でPythonの関数を直接呼んでいたが、
    今回は session.call_tool() を通じて「別プロセスのMCPサーバー」に
    実行を依頼している。LLM自身から見ると、呼び方(tools定義)は変わらない。

必要ライブラリ（MCPSrver.py 側と同じ理由でバージョン固定すること）:
    pip install "mcp[cli]<2" ollama
    
使い方
> ollama serve --model gemma4:e4b
> python3 MCPClientAgent.py
"""

import asyncio

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LLM_MODEL = "gemma4:e4b"
MAX_AGENT_TURNS = 5          # 1サイクルあたりのツール往復の上限（暴走防止）
LOOP_INTERVAL_SEC = 3600       # 何秒おきにエージェントを1サイクル動かすか

AGENT_INSTRUCTION = (
    "あなたは室内のLED表示を管理するエージェントです。\n"
    "まず get_temperature ツールで現在の室温を確認し、"
    "その結果を踏まえて set_led ツールで適切な色（red/yellow/green）に切り替えてください。\n"
    "作業が終わったら、何をどう判断したかを短く日本語で報告してください。"
)

# MCPServer.py を子プロセスとして起動するための設定
SERVER_PARAMS = StdioServerParameters(command="python3", args=["MCPServer.py"])


def mcp_tools_to_ollama_format(mcp_tools) -> list[dict]:
    """
    MCPサーバーが返すツール一覧(name/description/inputSchema)を、
    そのままOllamaのtools引数の形式に変換する。
    ここで人間が手でツール定義を書き写す必要がない、というのがMCPの効能のひとつ。
    """
    tools = []
    for t in mcp_tools:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
        )
    return tools


async def run_agent_step(session: ClientSession, tools: list[dict]) -> str:
    """
    LLMにツール一式を渡し、LLM自身がget_temperature -> set_ledという
    手順を組み立てて実行するのに任せる。Pythonは、呼ばれたツールを
    MCP経由でサーバーに実行させ、結果をLLMに返す「取り次ぎ役」に徹する。
    """
    messages = [{"role": "user", "content": AGENT_INSTRUCTION}]

    for _ in range(MAX_AGENT_TURNS):
        response = ollama.chat(
            model=LLM_MODEL,
            messages=messages,
            tools=tools,
            think=False,
        )
        message = response["message"]
        tool_calls = message.get("tool_calls")

        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )

        if not tool_calls:
            return message.get("content") or "(報告なし)"

        for call in tool_calls:
            name = call.function.name
            args = call.function.arguments or {}

            # ここがこれまでとの一番の違い:
            # 直接Pythonの関数を呼ぶのではなく、MCPサーバーに実行を依頼する
            result = await session.call_tool(name, args)
            result_text = "".join(
                block.text for block in result.content if hasattr(block, "text")
            )
            print(f"  [MCPツール実行] {name}({args}) -> {result_text}")

            messages.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": result_text,
                }
            )

    return "(上限回数に達したため打ち切りました)"


async def main() -> None:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tool_list = await session.list_tools()
            tools = mcp_tools_to_ollama_format(tool_list.tools)
            print("MCPサーバーから取得したツール:", [t["function"]["name"] for t in tools])

            try:
                while True:
                    report = await run_agent_step(session, tools)
                    print(f"エージェントの報告: {report}")
                    await asyncio.sleep(LOOP_INTERVAL_SEC)
            except KeyboardInterrupt:
                print("\n終了します。")


if __name__ == "__main__":
    asyncio.run(main())
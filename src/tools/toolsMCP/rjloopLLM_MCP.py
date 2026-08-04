"""
Real Junk (RJ) - Perceive -> Decide -> Act ループ 最小実装
------------------------------------------------------
ステップ1: if文によるダミー判断でループ全体の配線を確認 済み。
ステップ2: decide_led() の中身をローカルLLM(Ollama)呼び出しに差し替え 済み。
ステップ3: プロンプトの外部ファイル化、外気温(Open-Meteo)入力の追加 済み。
ステップ4（今回）:
    - get_temperature / set_led を Ollama の Function Calling 用ツールとして定義
    - テキスト応答を正規表現でパースする方式から、LLMが自らツールを選んで呼び出す
      方式に変更。Pythonは「呼ばれたツールを実際に実行して結果を返す」役に徹する。

必要ライブラリ:
    pip install pyserial ollama
    ※ Ollama本体を起動し、Function Calling対応モデル(gemma4:e4b等)をpull済みであること
    ※ 外気温取得にはインターネット接続が必要（追加ライブラリ不要、標準のurllibを使用）
"""

import json
import time
import urllib.error
import urllib.request

import ollama
import serial

# ==== LLM設定 ====
LLM_MODEL = "gemma4:e4b"
MAX_AGENT_TURNS = 5  # 1回の判断あたり、ツール呼び出しの往復を打ち切るまでの上限

# LLMへの最初の指示文。{outdoor_temperature} には外気温が入る。
# 室内温度はここには含めない。LLM自身に get_temperature ツールで取得させる。
AGENT_INSTRUCTION = (
    "あなたは室内のLED表示を管理するエージェントです。\n"
    "外気温は{outdoor_temperature}です。\n"
    "まず get_temperature ツールで現在の室温を確認し、"
    "その結果を踏まえて set_led ツールで適切な色（red/yellow/green）に切り替えてください。\n"
    "作業が終わったら、何をどう判断したかを短く日本語で報告してください。"
)

# ==== 気象情報設定（Open-Meteo, APIキー不要） ====
# デフォルトは千葉県習志野市付近。必要に応じて変更してください。
WEATHER_LATITUDE =  43.2121677103198
WEATHER_LONGITUDE = 141.74252667067037
WEATHER_API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LATITUDE}&longitude={WEATHER_LONGITUDE}"
    "&current=temperature_2m"
)

# ==== シリアル設定（環境に合わせて変更してください） ====
SERIAL_PORT = "/dev/tty.usbmodemBDD28F0643042"
BAUD_RATE = 115200
LOOP_INTERVAL_SEC = 15  # 何秒おきにエージェントを1サイクル動かすか

# LED色 -> (点灯コマンド, 消灯コマンド)
LED_COMMANDS = {
    "red": ("R", "r"),
    "yellow": ("Y", "y"),
    "green": ("G", "g"),
}

# ==== Ollama Function Calling 用のツール定義 ====
# description欄がLLMへの「このツールは何のためのものか」という唯一の手がかりになる。
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_temperature",
            "description": "室内の温度センサから現在の室温（摂氏）を取得する。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_led",
            "description": (
                "室内の状態表示LEDを指定した色に切り替える。"
                "redは高温警告、yellowは注意、greenは平常を意味する。"
                "指定した色以外は自動的に消灯される。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "color": {
                        "type": "string",
                        "enum": ["red", "yellow", "green"],
                        "description": "点灯させたいLEDの色",
                    }
                },
                "required": ["color"],
            },
        },
    },
]


def fetch_outdoor_temperature() -> str:
    """
    Open-Meteo API から現在の外気温を取得する。
    取得できなければ "不明" を返し、ループは継続する。
    """
    try:
        with urllib.request.urlopen(WEATHER_API_URL, timeout=5) as res:
            data = json.loads(res.read().decode("utf-8"))
        temp = data["current"]["temperature_2m"]
        return f"{temp:.1f}度"
    except (urllib.error.URLError, KeyError, ValueError) as e:
        print(f"  [警告] 外気温の取得に失敗しました: {e}")
        return "不明"


def open_connection() -> serial.Serial:
    """シリアルポートをオープンする"""
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
    time.sleep(2)  # マイコン側のリセット待ち（USBシリアル変換基板がリセットをかける場合の保険）
    ser.reset_input_buffer()
    return ser


def send_command(ser: serial.Serial, command: str) -> None:
    """コマンドを改行付きで送信する"""
    ser.write((command + "\n").encode("ascii"))


# ==== ツールの「実体」。LLMからの呼び出しを受けて、実際にハードウェアを動かす ====

def tool_get_temperature(ser: serial.Serial, args: dict) -> dict:
    """
    'T' コマンドを送信し、'TEMP = ' で始まる行から温度を取得する。
    デバッグメッセージが混じっても無視して該当行だけ拾う。
    """
    send_command(ser, "T")

    deadline = time.time() + 3  # 最大3秒待つ
    while time.time() < deadline:
        line = ser.readline().decode("ascii", errors="ignore").strip()
        if not line:
            continue
        if line.startswith("TEMP = "):
            # 例: "TEMP = 23.43 C" -> 23.43
            value_part = line[len("TEMP = "):].split()[0]
            return {"temperature_celsius": float(value_part)}

    return {"error": "温度応答(TEMP = ...)が時間内に得られませんでした"}


def tool_set_led(ser: serial.Serial, args: dict) -> dict:
    """指定色だけを点灯し、他の色は消灯する"""
    color = args.get("color")
    if color not in LED_COMMANDS:
        return {"error": f"不正な色が指定されました: {color!r}"}

    commands = []
    for name, (on_cmd, off_cmd) in LED_COMMANDS.items():
        commands.append(on_cmd if name == color else off_cmd)
    send_command(ser, "".join(commands))
    return {"result": "ok", "color": color}


TOOL_IMPLEMENTATIONS = {
    "get_temperature": tool_get_temperature,
    "set_led": tool_set_led,
}


def run_agent_step(ser: serial.Serial, outdoor_temperature: str) -> str:
    """
    LLMにツール一式を渡し、LLMが自ら get_temperature -> set_led という
    手順を組み立てて実行するのに任せる。Pythonは呼ばれたツールを実行し、
    結果をLLMに返すだけの「実行係」に徹する。
    戻り値はLLMからの最終的な報告テキスト。
    """
    messages = [
        {
            "role": "user",
            "content": AGENT_INSTRUCTION.format(outdoor_temperature=outdoor_temperature),
        }
    ]

    for _ in range(MAX_AGENT_TURNS):
        response = ollama.chat(
            model=LLM_MODEL,
            messages=messages,
            tools=TOOLS,
            think=False,
        )
        message = response["message"]
        tool_calls = message.get("tool_calls")

        # 会話履歴に、今回のLLM応答をそのまま積む
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )

        if not tool_calls:
            # ツール呼び出しがなければ、これが最終回答
            return message.get("content") or "(報告なし)"

        for call in tool_calls:
            name = call.function.name
            args = call.function.arguments or {}
            implementation = TOOL_IMPLEMENTATIONS.get(name)

            if implementation is None:
                result = {"error": f"未知のツールが呼び出されました: {name}"}
            else:
                result = implementation(ser, args)
                print(f"  [ツール実行] {name}({args}) -> {result}")

            messages.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return "(上限回数に達したため打ち切りました)"


def main() -> None:
    ser = open_connection()
    print(f"接続しました: {SERIAL_PORT} @ {BAUD_RATE}bps")

    try:
        while True:
            outdoor_temperature = fetch_outdoor_temperature()
            print(f"外気温: {outdoor_temperature}")
            report = run_agent_step(ser, outdoor_temperature)
            print(f"エージェントの報告: {report}")
            time.sleep(LOOP_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n終了します。全LED消灯。")
        send_command(ser, "ryg")  # 念のため全消灯
    finally:
        ser.close()


if __name__ == "__main__":
    main()
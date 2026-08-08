"""
Real Junk (RJ) - MCP Server
----------------------------
get_temperature / set_led を「本物のMCPサーバー」として公開する。
これまでPythonプロセス内で完結していたツールの実体を、独立したプロセスに切り出す。
LLM(Ollama)を呼ぶクライアント側は、この関数の中身を一切知らなくても、
MCPプロトコル越しに「ツール名」「description」「引数スキーマ」だけを頼りに使える。

起動方法（単体テスト用。通常は MCPServerAgent.py がサブプロセスとして自動起動する）:
    python3 MCPServer.py

必要ライブラリ（MCP Python SDK は2026年に v2 へメジャーアップデートされ、
API に破壊的変更が入っている。このコードは安定している v1 系を前提にしているため、
必ずバージョンを固定してインストールすること）:
    pip install "mcp[cli]<2" pyserial
"""

import json
import time
import urllib.error
import urllib.request
import serial
from mcp.server.fastmcp import FastMCP

# ==== 気象情報設定（Open-Meteo, APIキー不要） ====
# デフォルトは北海道岩見沢市付近。必要に応じて変更してください。
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

# LED色 -> (点灯コマンド, 消灯コマンド)
LED_COMMANDS = {
    "red": ("R", "r"),
    "yellow": ("Y", "y"),
    "green": ("G", "g"),
}

mcp = FastMCP("real-junk")

# シリアルポートはサーバー起動時ではなく、初回アクセス時に遅延オープンする
# （サーバープロセスが起動しただけでマイコンをリセットしてしまうのを避けるため）
_ser: serial.Serial | None = None


def _get_serial() -> serial.Serial:
    global _ser
    if _ser is None:
        _ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
        time.sleep(2)  # マイコン側のリセット待ち
        _ser.reset_input_buffer()
    return _ser


def _send_command(command: str) -> None:
    _get_serial().write((command + "\n").encode("ascii"))


@mcp.tool()
def get_outdoor_temperature() -> str:
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

@mcp.tool()
def get_temperature() -> dict:
    """室内の温度センサから現在の室温（摂氏）を取得する。"""
    ser = _get_serial()
    _send_command("T")

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


@mcp.tool()
def set_led(color: str) -> dict:
    """
    室内の状態表示LEDを指定した色に切り替える。
    redは高温警告、yellowは注意、greenは平常を意味する。
    color引数には 'red', 'yellow', 'green' のいずれかを指定すること。
    """
    if color not in LED_COMMANDS:
        return {"error": f"不正な色が指定されました: {color!r}"}

    commands = []
    for name, (on_cmd, off_cmd) in LED_COMMANDS.items():
        commands.append(on_cmd if name == color else off_cmd)
    _send_command("".join(commands))
    return {"result": "ok", "color": color}


if __name__ == "__main__":
    # デフォルトでstdioトランスポートを使う。
    # 単体テストしたい場合は `mcp dev MCPServer.py` でInspectorから叩くこともできる。
    mcp.run()
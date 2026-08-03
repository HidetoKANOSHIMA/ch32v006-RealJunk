"""
Real Junk (RJ) - Perceive -> Decide -> Act ループ 最小実装
------------------------------------------------------
ステップ1: if文によるダミー判断でループ全体の配線を確認 済み。
ステップ2: decide_led() の中身をローカルLLM(Ollama)呼び出しに差し替え 済み。
ステップ3（今回）:
    - プロンプトをソースコード外部（ファイル or 標準入力）から読み込めるようにした
    - 外気温（Open-Meteo APIより取得）を追加入力とし、LLMに
      「LED色」と「室温の上昇/下降傾向」の2つを判断させるようにした

必要ライブラリ:
    pip install pyserial ollama
    ※ Ollama本体を起動し、モデル(gemma4:e4b等)をpull済みであること
    ※ 外気温取得にはインターネット接続が必要（追加ライブラリ不要、標準のurllibを使用）
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

import ollama
import serial

# ==== LLM設定 ====
LLM_MODEL = "gemma4:e4b"

# プロンプトが外部から与えられなかった場合のデフォルトテンプレート。
# {temperature} = 室内温度, {outdoor_temperature} = 外気温（取得失敗時は "不明"）
DEFAULT_PROMPT_TEMPLATE = (
    "現在の室内温度は{temperature:.2f}度、外気温は{outdoor_temperature}です。\n"
    "以下の2点を判断してください。\n"
    "1. この室温を示すLEDの色として最も適切なもの（red, yellow, green のいずれか1語）\n"
    "2. 外気温を踏まえて、今後室温が上昇するか下降するか、あるいは変化が少ないか"
    "（rising, falling, stable のいずれか1語）\n"
    "説明や理由は書かず、必ず次の2行だけを返してください。\n"
    "color: <red/yellow/green のいずれか>\n"
    "trend: <rising/falling/stable のいずれか>"
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
LOOP_INTERVAL_SEC = 5  # 何秒おきに温度を確認するか

# LED色 -> (点灯コマンド, 消灯コマンド)
LED_COMMANDS = {
    "red": ("R", "r"),
    "yellow": ("Y", "y"),
    "green": ("G", "g"),
}


def load_prompt_template() -> str:
    """
    プロンプトテンプレートの読み込み優先順位:
      1. --prompt-file で指定されたファイル
      2. 標準入力がパイプ/リダイレクトされていればそこから読む
      3. どちらもなければ DEFAULT_PROMPT_TEMPLATE を使う
    テンプレート内では {temperature} と {outdoor_temperature} が使えます。
    """
    parser = argparse.ArgumentParser(description="Real Junk loop")
    parser.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="プロンプトテンプレートを記述したテキストファイルのパス",
    )
    args = parser.parse_args()

    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            template = f.read().strip()
        print(f"プロンプトをファイルから読み込みました: {args.prompt_file}")
        return template

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            print("プロンプトを標準入力から読み込みました。")
            return piped

    print("デフォルトのプロンプトテンプレートを使用します。")
    return DEFAULT_PROMPT_TEMPLATE


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


def read_temperature(ser: serial.Serial) -> float:
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
            return float(value_part)

    raise TimeoutError("温度応答(TEMP = ...)が時間内に得られませんでした")


def decide_led_and_trend(prompt_template: str, temperature: float, outdoor_temperature: str) -> tuple[str, str]:
    """
    ローカルLLMに室内温度と外気温を渡し、(LED色, 室温の傾向) を判断させる。
    解釈に失敗した場合は、色は閾値ロジックに、傾向は "unknown" にフォールバックする。
    """
    prompt = prompt_template.format(
        temperature=temperature, outdoor_temperature=outdoor_temperature
    )

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=False,
    )
    reply = response["message"]["content"]

    color_match = re.search(r"\b(red|yellow|green)\b", reply, re.IGNORECASE)
    trend_match = re.search(r"\b(rising|falling|stable)\b", reply, re.IGNORECASE)

    if color_match:
        color = color_match.group(1).lower()
    else:
        print(f"  [警告] LLM応答からLED色を解釈できませんでした: {reply!r} -> フォールバック判断を使用")
        if temperature >= 28.0:
            color = "red"
        elif temperature >= 22.0:
            color = "yellow"
        else:
            color = "green"

    trend = trend_match.group(1).lower() if trend_match else "unknown"

    return color, trend


def set_led(ser: serial.Serial, color: str) -> None:
    """指定色だけを点灯し、他の色は消灯する"""
    commands = []
    for name, (on_cmd, off_cmd) in LED_COMMANDS.items():
        commands.append(on_cmd if name == color else off_cmd)
    send_command(ser, "".join(commands))


def main() -> None:
    prompt_template = load_prompt_template()
    ser = open_connection()
    print(f"接続しました: {SERIAL_PORT} @ {BAUD_RATE}bps")

    try:
        while True:
            temperature = read_temperature(ser)
            outdoor_temperature = fetch_outdoor_temperature()
            color, trend = decide_led_and_trend(prompt_template, temperature, outdoor_temperature)
            set_led(ser, color)
            print(
                f"室温: {temperature:.2f} C / 外気温: {outdoor_temperature} "
                f"-> LED: {color} / 傾向: {trend}"
            )
            time.sleep(LOOP_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n終了します。全LED消灯。")
        send_command(ser, "ryg")  # 念のため全消灯
    finally:
        ser.close()


if __name__ == "__main__":
    main()
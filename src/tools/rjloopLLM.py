"""
Real Junk (RJ) - Perceive -> Decide -> Act ループ 最小実装
------------------------------------------------------
ステップ1: if文によるダミー判断でループ全体の配線を確認 済み。
ステップ2（今回）: decide_led() の中身をローカルLLM(Ollama)呼び出しに差し替え。

必要ライブラリ:
    pip install pyserial ollama
    ※ Ollama本体を起動し、モデル(gemma4:e4b等)をpull済みであること
"""

import re

import ollama
import serial
import time

# ==== LLM設定 ====
LLM_MODEL = "gemma4:e4b"

# ==== 設定（環境に合わせて変更してください） ====
SERIAL_PORT = "/dev/tty.usbmodemBDD28F0643042"  # ご自身のUSBシリアル変換のデバイス名に変更
BAUD_RATE = 115200                              # readme記載の値。通信できなければ 115200 等も試してください
LOOP_INTERVAL_SEC = 5                           # 何秒おきに温度を確認するか

# LED色 -> (点灯コマンド, 消灯コマンド)
LED_COMMANDS = {
    "red": ("R", "r"),
    "yellow": ("Y", "y"),
    "green": ("G", "g"),
}


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


def decide_led(temperature: float) -> str:
    """
    ローカルLLMに温度を渡し、"red" / "yellow" / "green" のいずれかを判断させる。
    応答の解釈に失敗した場合は、以前のダミー判断ロジックにフォールバックする。
    """
    prompt = (
        f"現在の温度は{temperature:.2f}度です。"
        "これは成人男子が寒いと感じる温度です。"        # これを入れると判断が揺らぐ
        "この温度を示すLEDの色として最も適切なものを "
        "red, yellow, green の3語のうち1語だけで答えてください。"
        "説明や理由は不要です。単語のみを返してください。"
    )

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        think=True,
    )
    reply = response["message"]["content"]

    # 応答文の中から red/yellow/green のいずれかを拾う（前後に余計な語が付いても対応）
    match = re.search(r"\b(red|yellow|green)\b", reply, re.IGNORECASE)
    if match:
        print(f"  [LLM応答] {reply!r} -> LED: {match.group(1).lower()}")
        return match.group(1).lower()

    print(f"  [警告] LLM応答を解釈できませんでした: {reply!r} -> フォールバック判断を使用")
    if temperature >= 28.0:
        return "red"
    elif temperature >= 22.0:
        return "yellow"
    else:
        return "green"


def set_led(ser: serial.Serial, color: str) -> None:
    """指定色だけを点灯し、他の色は消灯する"""
    commands = []
    for name, (on_cmd, off_cmd) in LED_COMMANDS.items():
        commands.append(on_cmd if name == color else off_cmd)
    send_command(ser, "".join(commands))


def main() -> None:
    ser = open_connection()
    print(f"接続しました: {SERIAL_PORT} @ {BAUD_RATE}bps")

    try:
        while True:
            temperature = read_temperature(ser)
            color = decide_led(temperature)
            set_led(ser, color)
            print(f"温度: {temperature:.2f} C -> LED: {color}")
            time.sleep(LOOP_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\n終了します。全LED消灯。")
        send_command(ser, "ryg")  # 念のため全消灯
    finally:
        ser.close()


if __name__ == "__main__":
    main()
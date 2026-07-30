"""
Real Junk (RJ) - Perceive -> Decide -> Act ループ 最小実装
------------------------------------------------------
ステップ1: LLMを使わず、if文によるダミー判断でループ全体の配線を確認する。
ステップ2（今後）: decide_led() の中身をローカルLLM呼び出しに差し替える。

必要ライブラリ:
    pip install pyserial
"""

import serial
import time

# ==== 設定（環境に合わせて変更してください） ====
SERIAL_PORT = "/dev/tty.usbserial-XXXX"  # ご自身のUSBシリアル変換のデバイス名に変更
BAUD_RATE = 15200                         # readme記載の値。通信できなければ 115200 等も試してください
LOOP_INTERVAL_SEC = 5                     # 何秒おきに温度を確認するか

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
    ダミー判断ロジック（後でLLM呼び出しに差し替える部分）。
    温度に応じて "red" / "yellow" / "green" を返す。
    """
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
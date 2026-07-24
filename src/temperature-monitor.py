#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
温度モニタリング通信プログラム
----------------------------------
動作環境: macOS (Tahoe) / Mac mini M4
接続構成: Mac mini M4 <--USBシリアル変換基板--> CH32V006 マイコン基板 <--> 温度センサ / LED(赤・黄・緑)

■ マイコン基板側の仕様(前提)
  'T' 受信 -> 温度をシリアルへ返信 (例: "27,5" -> 27.5℃)
  'R'/'r'  -> LED-RED   点灯/消灯
  'Y'/'y'  -> LED-YELLOW 点灯/消灯
  'G'/'g'  -> LED-GREEN 点灯/消灯
  '#'      -> 1000ms 休止

■ このプログラムの仕様
  1. 起動時: 'T'コマンドで室温を3回測定(各測定の間に10秒待機)し、平均値を基準温度として記憶する。
  2. 以後10秒おきに'T'コマンドで室温を取得する。
  3. 基準温度より高ければ赤LEDを3回点滅、低ければ緑LEDを3回点滅、
     同じであれば黄LEDを3回点滅させるコマンド列を送信する。

■ 事前準備
  pip install pyserial

■ 実行例
  python3 temperature_monitor.py
  python3 temperature_monitor.py --port /dev/tty.usbserial-XXXX --baud 115200

※ ボーレートはマイコン側ファームウェアの設定に合わせて --baud で調整してください
  (デフォルトは一般的な 115200 を想定しています)。
※ マイコンからの温度応答は改行区切り(例: "27,5\\n")を想定しています。
  実機のファームウェアが異なる終端文字を使う場合は read_temperature() を調整してください。
"""

import argparse
import glob
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("エラー: pyserial がインストールされていません。`pip install pyserial` を実行してください。", file=sys.stderr)
    sys.exit(1)


# ----------------------------------------------------------------------------
# 設定値
# ----------------------------------------------------------------------------
DEFAULT_BAUDRATE = 115200      # マイコン側ファームウェアに合わせて要調整
SERIAL_TIMEOUT = 3.0           # 応答待ちタイムアウト(秒)
MEASURE_INTERVAL = 10.0        # 定常監視時の測定間隔(秒)
INITIAL_SAMPLE_COUNT = 3       # 起動時キャリブレーションの測定回数
BLINK_UNIT_SEC = 1.0           # マイコン側 '#' の休止時間(秒) = 1000ms

# 3回点滅コマンド列(仕様書の例をそのまま使用)
BLINK_RED = "R#r#R#r#R#r"
BLINK_GREEN = "G#g#G#g#G#g"
BLINK_YELLOW = "Y#y#Y#y#Y#y"


# ----------------------------------------------------------------------------
# シリアルポートの自動検出
# ----------------------------------------------------------------------------
def find_usb_serial_port() -> Optional[str]:
    """接続中のUSBシリアル変換基板のデバイスパスを自動検出する"""
    keywords = ("usbserial", "usbmodem", "wchusbserial", "wchusbmodem")

    for p in list_ports.comports():
        if any(k in p.device.lower() for k in keywords):
            return p.device

    # list_ports で見つからない場合のフォールバック
    for pattern in ("/dev/tty.usbserial*", "/dev/tty.usbmodem*", "/dev/tty.wchusbserial*"):
        found = glob.glob(pattern)
        if found:
            return found[0]

    return None


# ----------------------------------------------------------------------------
# マイコンとのシリアル通信ラッパー
# ----------------------------------------------------------------------------
class McuLink:
    """CH32V006マイコン基板とのシリアル通信を担当するクラス"""

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE, timeout: float = SERIAL_TIMEOUT):
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        # USB-CDC系マイコンはポートオープン時にリセットがかかる場合があるため待機
        time.sleep(2.0)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _write(self, text: str):
        self.ser.write(text.encode("ascii"))
        self.ser.flush()

    def read_temperature(self) -> float:
        """'T'コマンドを送信し、応答("27,5"のような文字列)を温度(float)に変換して返す"""
        self.ser.reset_input_buffer()
        self._write("T")

        line = self.ser.readline()
        if not line:
            raise TimeoutError("マイコンから温度応答がありませんでした(タイムアウト)")

        text = line.decode("ascii", errors="ignore").strip()
        if not text:
            raise ValueError("空の応答を受信しました")

        try:
            integer_part, decimal_part = text.split(",")
            temperature = float(f"{integer_part}.{decimal_part}")
        except ValueError as e:
            raise ValueError(f"温度応答の解析に失敗しました: '{text}'") from e

        return temperature

    def blink(self, command: str):
        """LED点滅コマンド列を送信し、マイコン側の休止時間の合計だけ待機する"""
        self._write(command)
        pause_count = command.count("#")
        time.sleep(pause_count * BLINK_UNIT_SEC)


# ----------------------------------------------------------------------------
# 温度監視ロジック
# ----------------------------------------------------------------------------
@dataclass
class TemperatureMonitor:
    link: McuLink
    baseline: Optional[float] = None

    def calibrate(self, samples: int = INITIAL_SAMPLE_COUNT, interval: float = MEASURE_INTERVAL) -> float:
        """起動時キャリブレーション: samples回測定し、平均を基準温度とする"""
        readings = []
        for i in range(samples):
            t = self.link.read_temperature()
            readings.append(t)
            print(f"[起動時測定 {i + 1}/{samples}] 室温: {t:.1f} ℃")
            if i < samples - 1:
                time.sleep(interval)

        self.baseline = statistics.mean(readings)
        print(f"基準温度(平均): {self.baseline:.2f} ℃\n")
        return self.baseline

    def evaluate_and_signal(self, temperature: float):
        """測定温度を基準温度と比較し、対応するLED点滅コマンドを送信する"""
        assert self.baseline is not None

        if temperature > self.baseline:
            print(f"室温 {temperature:.1f} ℃ > 基準 {self.baseline:.2f} ℃  -> 赤色LED 3回点滅")
            self.link.blink(BLINK_RED)
        elif temperature < self.baseline:
            print(f"室温 {temperature:.1f} ℃ < 基準 {self.baseline:.2f} ℃  -> 緑色LED 3回点滅")
            self.link.blink(BLINK_GREEN)
        else:
            print(f"室温 {temperature:.1f} ℃ = 基準 {self.baseline:.2f} ℃  -> 黄色LED 3回点滅")
            self.link.blink(BLINK_YELLOW)


# ----------------------------------------------------------------------------
# メイン処理
# ----------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="CH32V006 温度モニタリング通信プログラム")
    parser.add_argument("--port", "-p", default=None,
                         help="シリアルポート (例: /dev/tty.usbserial-XXXX)。省略時は自動検出")
    parser.add_argument("--baud", "-b", type=int, default=DEFAULT_BAUDRATE,
                         help=f"ボーレート (デフォルト: {DEFAULT_BAUDRATE})")
    parser.add_argument("--interval", type=float, default=MEASURE_INTERVAL,
                         help=f"測定間隔・秒 (デフォルト: {MEASURE_INTERVAL})")
    return parser.parse_args()


def main():
    args = parse_args()

    port = args.port or find_usb_serial_port()
    if port is None:
        print("エラー: USBシリアル変換基板が見つかりません。--port で明示的に指定してください。", file=sys.stderr)
        print("現在認識されているシリアルポート:", file=sys.stderr)
        for p in list_ports.comports():
            print(f"  {p.device} - {p.description}", file=sys.stderr)
        sys.exit(1)

    print(f"シリアルポート: {port} (baud={args.baud})")

    try:
        link = McuLink(port=port, baudrate=args.baud)
    except serial.SerialException as e:
        print(f"シリアルポートのオープンに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    monitor = TemperatureMonitor(link=link)

    try:
        # 1. 起動時キャリブレーション(3回測定・平均を基準温度に)
        monitor.calibrate(samples=INITIAL_SAMPLE_COUNT, interval=args.interval)

        print("監視を開始します。Ctrl+C で終了します。\n")

        # 2. 以後、10秒おきの測定サイクルを維持する
        #    (LED点滅にかかる時間を差し引いて、次回測定が10秒間隔からずれないように調整)
        next_measure_at = time.monotonic() + args.interval

        while True:
            now = time.monotonic()
            wait = next_measure_at - now
            if wait > 0:
                time.sleep(wait)
            next_measure_at += args.interval

            try:
                temperature = link.read_temperature()
            except (TimeoutError, ValueError) as e:
                print(f"警告: 温度取得に失敗しました ({e})。次回サイクルで再試行します。", file=sys.stderr)
                continue

            monitor.evaluate_and_signal(temperature)

    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        link.close()


if __name__ == "__main__":
    main()
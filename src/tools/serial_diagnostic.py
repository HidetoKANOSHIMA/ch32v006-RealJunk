#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
シリアル通信 診断スクリプト
----------------------------------
temperature_monitor.py がタイムアウトする原因を切り分けるための簡易ツール。
'T' を送信し、一定時間内に受信した生バイト列をそのまま表示する。

実行例:
  python3 serial_diagnostic.py --port /dev/cu.usbmodemBDD28F0643042 --baud 115200
  python3 serial_diagnostic.py --port /dev/cu.usbmodemBDD28F0643042 --baud 115200 --wait 8
"""

import argparse
import sys
import time

import serial


def main():
    parser = argparse.ArgumentParser(description="シリアル通信診断ツール")
    parser.add_argument("--port", "-p", required=True, help="シリアルポート")
    parser.add_argument("--baud", "-b", type=int, default=115200, help="ボーレート")
    parser.add_argument("--wait", type=float, default=5.0, help="応答待ち時間(秒)")
    parser.add_argument("--startup-delay", type=float, default=2.0, help="ポートオープン後の待機時間(秒)")
    parser.add_argument("--char", default="T", help="送信する文字 (デフォルト: T)")
    parser.add_argument("--eol", default="lf", choices=["none", "lf", "cr", "crlf"],
                         help="送信データに付加する終端文字: none(なし)/lf(\\n)/cr(\\r)/crlf(\\r\\n) (デフォルト: lf)")
    args = parser.parse_args()

    eol_map = {"none": "", "lf": "\n", "cr": "\r", "crlf": "\r\n"}
    payload = args.char + eol_map[args.eol]

    print(f"ポート {args.port} を baud={args.baud} でオープンします...")
    try:
        ser = serial.Serial(port=args.port, baudrate=args.baud, timeout=0.5)
    except serial.SerialException as e:
        print(f"オープン失敗: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"現在の制御線状態: DTR={ser.dtr}, RTS={ser.rts}, CTS={ser.cts}, DSR={ser.dsr}, CD={ser.cd}")
    print(f"{args.startup_delay}秒待機します(MCU再起動対策)...")
    time.sleep(args.startup_delay)

    ser.reset_input_buffer()
    ser.reset_output_buffer()

    print(f"送信データ: {payload!r} を送信します...")
    ser.write(payload.encode("ascii"))
    ser.flush()

    print(f"{args.wait}秒間、受信データを監視します...")
    deadline = time.monotonic() + args.wait
    collected = bytearray()
    while time.monotonic() < deadline:
        chunk = ser.read(64)
        if chunk:
            collected.extend(chunk)
            print(f"  受信: {chunk!r}  (hex: {chunk.hex()})")

    print()
    if collected:
        print(f"合計 {len(collected)} バイト受信しました: {bytes(collected)!r}")
        try:
            print(f"ASCIIデコード: '{collected.decode('ascii', errors='replace')}'")
        except Exception:
            pass
    else:
        print("何も受信できませんでした。")
        print("考えられる原因:")
        print("  - ボーレート不一致")
        print("  - マイコン側ファームウェアが'T'コマンドを実装していない/起動していない")
        print("  - 配線(TX/RX)の未接続または逆接続")
        print("  - マイコンがリセット待ち/USB再enumeration中")

    ser.close()


if __name__ == "__main__":
    main()
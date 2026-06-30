///////////////////////////////////////
// ds18b20.h  - DS18B20 Library      //
// 1-Wire / GPIOC Pin0               //
///////////////////////////////////////
#ifndef DS18B20_H_
#define DS18B20_H_

#include "debug.h"
#include <stdint.h>

// --- ピン設定 ---
#define OW_PORT         GPIOC
#define OW_PIN          GPIO_Pin_0
#define OW_RCC          RCC_PB2Periph_GPIOC

// --- 1-Wire ROMコマンド ---
#define OW_CMD_SEARCH_ROM   0xF0
#define OW_CMD_READ_ROM     0x33
#define OW_CMD_MATCH_ROM    0x55
#define OW_CMD_SKIP_ROM     0xCC

// --- DS18B20 ファンクションコマンド ---
#define DS_CMD_CONVERT_T        0x44
#define DS_CMD_READ_SCRATCHPAD  0xBE
#define DS_CMD_WRITE_SCRATCHPAD 0x4E

// --- スクラッチパッド構成 ---
#define DS_SCRATCHPAD_SIZE  9
#define DS_IDX_TEMP_LSB     0
#define DS_IDX_TEMP_MSB     1
#define DS_IDX_CONFIG       4
#define DS_IDX_CRC          8

// --- 分解能設定 ---
#define DS_RES_9BIT     0x1F    // 変換時間  94ms
#define DS_RES_10BIT    0x3F    // 変換時間 188ms
#define DS_RES_11BIT    0x5F    // 変換時間 375ms
#define DS_RES_12BIT    0x7F    // 変換時間 750ms（デフォルト）

// --- ROM ID サイズ ---
#define OW_ROM_SIZE     8

// --- エラーコード ---
#define DS_OK           0
#define DS_ERR_NO_DEV   1       // プレゼンスパルスなし
#define DS_ERR_CRC      2       // CRCエラー

// --- ROM IDを格納する型 ---
typedef struct {
    uint8_t id[OW_ROM_SIZE];    // id[0]=ファミリコード, id[7]=CRC
} ds18b20_rom_t;

// --- 公開API ---

// GPIO初期化（プログラム起動時に1回呼ぶ）
void ds18b20_init(void);

// バス上のROM IDを1件読み出す（センサ1個接続時）
// rom: 読み出し先, 戻り値: DS_OK / DS_ERR_NO_DEV / DS_ERR_CRC
uint8_t ds18b20_read_rom(ds18b20_rom_t *rom);

// 指定ROMに温度変換～スクラッチパッド読み出しを行い生データを返す
// raw_temp: 符号付き16bit生値（1LSB = 1/16℃）
// 戻り値: DS_OK / DS_ERR_NO_DEV / DS_ERR_CRC
uint8_t ds18b20_read_temp_raw(const ds18b20_rom_t *rom, int16_t *raw_temp);

// 生データを hundredths-of-degree（例：2350 = 23.50℃）に変換
// 負温度対応済み
int32_t ds18b20_raw_to_hundredths(int16_t raw_temp);

// CRC8計算（Dallas/Maxim方式）
uint8_t ds18b20_crc8(const uint8_t *data, uint8_t len);

#endif /* DS18B20_H_ */
///////////////////////////////////////
// ds18b20.c  - DS18B20 Library      //
// 1-Wire / GPIOC Pin0               //
///////////////////////////////////////
#include "ds18b20.h"

// =============================================
// 内部: GPIO ヘルパー
// =============================================

// バスをLowに駆動
static inline void ow_pull_low(void) {
    GPIO_ResetBits(OW_PORT, OW_PIN);
}

// バスをリリース（オープンドレインなのでプルアップがHighに引き上げる）
static inline void ow_release(void) {
    GPIO_SetBits(OW_PORT, OW_PIN);
}

// バスの現在値を読む
static inline uint8_t ow_read_bit_raw(void) {
    return (uint8_t)GPIO_ReadInputDataBit(OW_PORT, OW_PIN);
}

// =============================================
// 内部: 1-Wire 基本操作
// =============================================

// リセット → 戻り値: 0=デバイスあり / 1=デバイスなし
static uint8_t ow_reset(void) {
    uint8_t presence;
    ow_pull_low();
    Delay_Us(500);      // リセットパルス（480µs以上）
    ow_release();
    Delay_Us(70);       // プレゼンスパルス待ち（60〜120µs）
    presence = ow_read_bit_raw();  // 0ならデバイスがパルスを返している
    Delay_Us(430);      // スロット残り時間を消費（合計1ms確保）
    return presence;    // 0=OK, 1=NG
}

// 1ビット送信
static void ow_write_bit(uint8_t bit) {
    if (bit) {
        // Write 1: 短いLow後すぐリリース
        ow_pull_low();  Delay_Us(6);
        ow_release();   Delay_Us(64);
    } else {
        // Write 0: スロット全体をLowで保持
        ow_pull_low();  Delay_Us(60);
        ow_release();   Delay_Us(10);
    }
}

// 1バイト送信（LSBファースト）
static void ow_write_byte(uint8_t data) {
    uint8_t i;
    for (i = 0; i < 8; i++) {
        ow_write_bit(data & 0x01);
        data >>= 1;
    }
}

// 1ビット受信
static uint8_t ow_read_bit(void) {
    uint8_t bit;
    ow_pull_low();      Delay_Us(3);    // 最低1µsのLow
    ow_release();       Delay_Us(10);   // サンプリングまで待つ（15µs以内）
    bit = ow_read_bit_raw();
    Delay_Us(55);       // スロット残り消費
    return bit;
}

// 1バイト受信（LSBファースト）
static uint8_t ow_read_byte(void) {
    uint8_t i, data = 0;
    for (i = 0; i < 8; i++) {
        data >>= 1;
        if (ow_read_bit()) {
            data |= 0x80;
        }
    }
    return data;
}

// =============================================
// 公開API実装
// =============================================

void ds18b20_init(void) {
    GPIO_InitTypeDef GPIO_InitStructure = {0};
    RCC_PB2PeriphClockCmd(OW_RCC, ENABLE);
    GPIO_InitStructure.GPIO_Pin   = OW_PIN;
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_Out_OD;   // オープンドレイン出力
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_Init(OW_PORT, &GPIO_InitStructure);
    ow_release();   // アイドル状態（High）
}

// CRC8 (Dallas/Maxim, 多項式 x^8+x^5+x^4+1)
uint8_t ds18b20_crc8(const uint8_t *data, uint8_t len) {
    uint8_t crc = 0, i;
    while (len--) {
        uint8_t byte = *data++;
        for (i = 0; i < 8; i++) {
            uint8_t mix = (crc ^ byte) & 0x01;
            crc >>= 1;
            if (mix) crc ^= 0x8C;
            byte >>= 1;
        }
    }
    return crc;
}

// ROM ID読み出し（センサ1個接続専用: READ ROM 0x33）
uint8_t ds18b20_read_rom(ds18b20_rom_t *rom) {
    uint8_t i;

    if (ow_reset() != 0) return DS_ERR_NO_DEV;

    ow_write_byte(OW_CMD_READ_ROM);
    for (i = 0; i < OW_ROM_SIZE; i++) {
        rom->id[i] = ow_read_byte();
    }

    // ROM ID末尾バイトはCRC8
    if (ds18b20_crc8(rom->id, 7) != rom->id[7]) return DS_ERR_CRC;

    return DS_OK;
}

// 温度読み出し（指定ROMにMATCH ROMで通信）
uint8_t ds18b20_read_temp_raw(const ds18b20_rom_t *rom, int16_t *raw_temp) {
    uint8_t i;
    uint8_t scratchpad[DS_SCRATCHPAD_SIZE];

    // --- 温度変換開始 ---
    if (ow_reset() != 0) return DS_ERR_NO_DEV;
    ow_write_byte(OW_CMD_MATCH_ROM);
    for (i = 0; i < OW_ROM_SIZE; i++) {
        ow_write_byte(rom->id[i]);
    }
    ow_write_byte(DS_CMD_CONVERT_T);

    Delay_Ms(800);      // 12bit分解能の変換時間（最大750ms）を余裕を持って待つ

    // --- スクラッチパッド読み出し ---
    if (ow_reset() != 0) return DS_ERR_NO_DEV;
    ow_write_byte(OW_CMD_MATCH_ROM);
    for (i = 0; i < OW_ROM_SIZE; i++) {
        ow_write_byte(rom->id[i]);
    }
    ow_write_byte(DS_CMD_READ_SCRATCHPAD);

    for (i = 0; i < DS_SCRATCHPAD_SIZE; i++) {
        scratchpad[i] = ow_read_byte();
    }

    // CRC検証（9バイト目がCRC）
    if (ds18b20_crc8(scratchpad, 8) != scratchpad[DS_IDX_CRC]) return DS_ERR_CRC;

    // 生温度データ（符号付き16bit）
    *raw_temp = (int16_t)((scratchpad[DS_IDX_TEMP_MSB] << 8) | scratchpad[DS_IDX_TEMP_LSB]);

    return DS_OK;
}

// 生値 → 百分の一度単位に変換（例: 2350 = 23.50℃, -550 = -5.50℃）
int32_t ds18b20_raw_to_hundredths(int16_t raw_temp) {
    return (int32_t)raw_temp * 100 / 16;
}
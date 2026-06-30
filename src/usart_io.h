#ifndef USART_IO_H_
#define USART_IO_H_

#include "ch32v00x.h"
#include <stdint.h>

// --- 公開API ---

// USART1をTX/RX両方有効、割り込み受信で初期化（baudrate指定）
void usart_io_init(uint32_t baudrate);

// 受信バッファから1バイト取得。データなければ -1
int usart_io_getchar(void);

// 受信バッファに1行分（'\n'まで）データがあるか確認
// 戻り値: 0=なし, 1=あり
uint8_t usart_io_line_available(void);

// 1行読み出し（'\n'まで、末尾'\0'付与）。バッファサイズ超過分は破棄
// 戻り値: 読み出した文字数（'\0'除く）
int usart_io_read_line(char *buf, uint8_t bufsize);

#endif /* USART_IO_H_ */
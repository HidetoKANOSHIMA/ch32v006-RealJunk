///////////////////////////////////////
// usart_io.c - USART1 TX/RX + RingBuf //
// PD5=TX, PD6=RX                      //
///////////////////////////////////////
#include "usart_io.h"
#include <stdio.h>

// =============================================
// 受信用リングバッファ（割り込みで書き込み）
// =============================================
#define RX_BUF_SIZE  32   // 2のべき乗
#define RX_BUF_MASK  (RX_BUF_SIZE - 1)

static volatile uint8_t rx_buf[RX_BUF_SIZE];
static volatile uint8_t rx_w = 0;
static volatile uint8_t rx_r = 0;

static inline int rx_push(uint8_t c) {
    uint8_t next = (rx_w + 1) & RX_BUF_MASK;
    if (next == rx_r) return -1;   // full（最古データ優先で破棄）
    rx_buf[rx_w] = c;
    rx_w = next;
    return 0;
}

int usart_io_getchar(void) {
    if (rx_r == rx_w) return -1;   // empty
    uint8_t c = rx_buf[rx_r];
    rx_r = (rx_r + 1) & RX_BUF_MASK;
    return (int)c;
}

uint8_t usart_io_line_available(void) {
    uint8_t r = rx_r;
    while (r != rx_w) {
        if (rx_buf[r] == '\n') return 1;
        r = (r + 1) & RX_BUF_MASK;
    }
    return 0;
}

int usart_io_read_line(char *buf, uint8_t bufsize) {
    int n = 0;
    int c;
    while ((c = usart_io_getchar()) != -1) {
        if (c == '\n') {
            break;
        }
        if (c == '\r') {
            continue;   // CR無視
        }
        if (n < (int)(bufsize - 1)) {
            buf[n++] = (char)c;
        }
        // バッファ超過分は読み捨て（行は最後まで消費する）
    }
    buf[n] = '\0';
    return n;
}

// =============================================
// 初期化
// =============================================

// printf用 putchar 実装（標準ライブラリのfputc/_writeから呼ばれる）
/**
int _write(int fd, char *buf, int size) {
    int i;
    for (i = 0; i < size; i++) {
        while (USART_GetFlagStatus(USART1, USART_FLAG_TC) == RESET);
        USART_SendData(USART1, (uint8_t)buf[i]);
    }
    return size;
}
*/

void usart_io_init(uint32_t baudrate) {
    GPIO_InitTypeDef  GPIO_InitStructure  = {0};
    USART_InitTypeDef USART_InitStructure = {0};
    NVIC_InitTypeDef  NVIC_InitStructure  = {0};

    RCC_PB2PeriphClockCmd(RCC_PB2Periph_GPIOD | RCC_PB2Periph_USART1, ENABLE);

    // PD5 = TX, プッシュプル出力
    GPIO_InitStructure.GPIO_Pin   = GPIO_Pin_5;
    GPIO_InitStructure.GPIO_Speed = GPIO_Speed_30MHz;
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_AF_PP;
    GPIO_Init(GPIOD, &GPIO_InitStructure);

    // PD6 = RX, 浮動入力
    GPIO_InitStructure.GPIO_Pin   = GPIO_Pin_6;
    GPIO_InitStructure.GPIO_Mode  = GPIO_Mode_IN_FLOATING;
    GPIO_Init(GPIOD, &GPIO_InitStructure);

    USART_InitStructure.USART_BaudRate            = baudrate;
    USART_InitStructure.USART_WordLength          = USART_WordLength_8b;
    USART_InitStructure.USART_StopBits            = USART_StopBits_1;
    USART_InitStructure.USART_Parity              = USART_Parity_No;
    USART_InitStructure.USART_Mode                = USART_Mode_Rx | USART_Mode_Tx;
    USART_InitStructure.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    USART_Init(USART1, &USART_InitStructure);

    // 受信割り込み有効化
    USART_ITConfig(USART1, USART_IT_RXNE, ENABLE);

    NVIC_InitStructure.NVIC_IRQChannel                   = USART1_IRQn;
    NVIC_InitStructure.NVIC_IRQChannelPreemptionPriority = 1;
    NVIC_InitStructure.NVIC_IRQChannelSubPriority        = 0;
    NVIC_InitStructure.NVIC_IRQChannelCmd                = ENABLE;
    NVIC_Init(&NVIC_InitStructure);

    USART_Cmd(USART1, ENABLE);
}

// =============================================
// 割り込みハンドラ
// =============================================
void USART1_IRQHandler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void USART1_IRQHandler(void) {
    if (USART_GetITStatus(USART1, USART_IT_RXNE) != RESET) {
        uint8_t c = (uint8_t)USART_ReceiveData(USART1);
        rx_push(c);
        // フラグはUSART_ReceiveDataの読み出しで自動クリアされる
    }
}
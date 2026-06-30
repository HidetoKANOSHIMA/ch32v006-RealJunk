// gpio_helper.h

#ifndef GPIO_HELPER_H
#define GPIO_HELPER_H

#include "ch32v00x.h"
#include <stdint.h>

/* ─── ピン記述子 ─── */
typedef struct {
    GPIO_TypeDef *port;   // GPIOA, GPIOC, GPIOD
    uint16_t      pin;    // GPIO_Pin_0 … GPIO_Pin_7
    uint8_t       active; // 0=ActiveLow, 1=ActiveHigh
} GpioPin;

/* ─── 方向 ─── */
typedef enum {
    GPIO_DIR_IN,
    GPIO_DIR_OUT
} GpioDir;

/* ─── API ─── */
void gpio_init(const GpioPin *p, GpioDir dir);
void gpio_write(const GpioPin *p, uint8_t on);  // 論理値(active考慮)
uint8_t gpio_read(const GpioPin *p);             // 論理値(active考慮)
void gpio_toggle(const GpioPin *p);

/* ブロッキング待機（タイムアウト: 0=永久） */
uint8_t gpio_wait_on (const GpioPin *p, uint32_t timeout_ms);
uint8_t gpio_wait_off(const GpioPin *p, uint32_t timeout_ms);

#endif
// gpio_helper.c

#include "gpio_helper.h"

/* ポートクロック有効化（重複呼び出しは無害） */
static void _enable_clock(GPIO_TypeDef *port)
{
    uint32_t mask = 0;
    if      (port == GPIOA) mask = RCC_PB2Periph_GPIOA;
    else if (port == GPIOB) mask = RCC_PB2Periph_GPIOB;
    else if (port == GPIOC) mask = RCC_PB2Periph_GPIOC;
    else if (port == GPIOD) mask = RCC_PB2Periph_GPIOD;
    if (mask) RCC_PB2PeriphClockCmd(mask, ENABLE);
}

void gpio_init(const GpioPin *p, GpioDir dir)
{
    GPIO_InitTypeDef cfg;
    _enable_clock(p->port);
    cfg.GPIO_Pin  = p->pin;
    cfg.GPIO_Speed = GPIO_Speed_30MHz;
    cfg.GPIO_Mode  = (dir == GPIO_DIR_OUT)
                     ? GPIO_Mode_Out_PP
                     : GPIO_Mode_IPU;   // 入力はプルアップをデフォルト
    GPIO_Init(p->port, &cfg);
}

void gpio_write(const GpioPin *p, uint8_t on)
{
    uint8_t level = p->active ? on : !on;
    if (level) GPIO_SetBits  (p->port, p->pin);
    else       GPIO_ResetBits(p->port, p->pin);
}

uint8_t gpio_read(const GpioPin *p)
{
    uint8_t raw = (GPIO_ReadInputDataBit(p->port, p->pin) != Bit_RESET);
    return p->active ? raw : !raw;   // active考慮した論理値を返す
}

void gpio_toggle(const GpioPin *p)
{
    p->port->OUTDR ^= p->pin;   // レジスタ直叩きで1命令
}

/* ── 待機系（SysTick依存。delay_ms が使える前提） ── */
extern void Delay_Ms(uint32_t n);   // MounRiver標準

uint8_t gpio_wait_on(const GpioPin *p, uint32_t timeout_ms)
{
    uint32_t elapsed = 0;
    while (!gpio_read(p)) {
        if (timeout_ms && elapsed >= timeout_ms) return 0;  // タイムアウト
        Delay_Ms(1);
        elapsed++;
    }
    return 1;   // ON検出
}

uint8_t gpio_wait_off(const GpioPin *p, uint32_t timeout_ms)
{
    uint32_t elapsed = 0;
    while (gpio_read(p)) {
        if (timeout_ms && elapsed >= timeout_ms) return 0;
        Delay_Ms(1);
        elapsed++;
    }
    return 1;   // OFF検出
}
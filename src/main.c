//#include <ch32v00x.h>
//#include <ch32v00x_usart.h>
#include <debug.h>
#include <stdlib.h>
#include "ds18b20.h"
#include "gpio_helper.h"
#include "usart_io.h"

void NMI_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void HardFault_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
/**
 */

static const GpioPin LED    =   { GPIOC, GPIO_Pin_1, 1 }; 
static const GpioPin GREEN  =   { GPIOC, GPIO_Pin_2, 1 }; 
static const GpioPin YELLOW =   { GPIOC, GPIO_Pin_3, 1 }; 
static const GpioPin PILOT  =   { GPIOC, GPIO_Pin_4, 1 };
// ActiveHighなLEDの定義。Port---LED---GNDという接続。gpio_write(&LED, 1)で点灯、gpio_write(&LED, 0)で消灯。
// ActiveLowにしたい場合は最後の値を0にして、Port---LED---VDDという接続にします。gpio_write(&LED, 1)で消灯、gpio_write(&LED, 0)で点灯になります。
static const GpioPin BUTTON = { GPIOC, GPIO_Pin_5, 0 };
// ActiveLowなボタンの定義。Port---BUTTON---GNDという接続。押されるとGNDに落ちて論理値1になります。
// ActiveHighにしたい場合は最後の値を1にします。この場合はPort---BUTTON---VDDという接続になります。押されるとVDDに繋がって論理値1になります。

void gpio_helper_init(){
    gpio_init(&LED,       GPIO_DIR_OUT);
    gpio_init(&GREEN,     GPIO_DIR_OUT);
    gpio_init(&YELLOW,    GPIO_DIR_OUT);
    gpio_init(&PILOT,     GPIO_DIR_OUT);
    gpio_init(&BUTTON,    GPIO_DIR_IN);
}

 int main(void) {
    ds18b20_rom_t rom;
    int16_t  raw;
    int32_t  temp_hund;
    uint8_t  err;

    SystemCoreClockUpdate();
    Delay_Init();
    ds18b20_init();
    gpio_helper_init();
    //
    gpio_write(&PILOT, 1);        // LED Turn-ON(to High)
    gpio_wait_on(&BUTTON, 3000);
    gpio_write(&PILOT, 0);
//    gpio_wait_off(&BUTTON, 0);
    //
    usart_io_init(115200);
    Delay_Ms(20);
    printf("Startup system clock: %lu Hz\n", SystemCoreClock);
    // ROM ID取得（起動時1回）
    err = ds18b20_read_rom(&rom);
    if (err != DS_OK) {
        printf("ROM read error: %d\r\n", err);
        while(1);
    }
    printf("Command: 'T' or 't'to read temperature.\n");
    printf("Command: 'R' to Red    LED ON, 'r' to Red    LED OFF.\n");
    printf("Command: 'G' to Green  LED ON, 'g' to Green  LED OFF.\n");
    printf("Command: 'Y' to Yellow LED ON, 'y' to Yellow LED OFF.\n");
    printf("Command: 'Q' to quit and restart this program.\n");
    printf("ROM ID: %02X-%02X-%02X-%02X-%02X-%02X-%02X-%02X\n",
           rom.id[0], rom.id[1], rom.id[2], rom.id[3],
           rom.id[4], rom.id[5], rom.id[6], rom.id[7]);

    while (1) {
        if (usart_io_line_available()) {
            char line[128];
            usart_io_read_line(line, sizeof(line));
            printf("Received: %s\n", line);
            if (*line == 't') {
                printf("Reading temperature on demand...\n");
                err = ds18b20_read_temp_raw(&rom, &raw);
                if (err == DS_OK) {
                    temp_hund = ds18b20_raw_to_hundredths(raw);
                    // 負温度対応: 絶対値に分解してprintf
                    if (temp_hund < 0) {
                        printf("TEMP = -%ld.%02ld C\n",
                       (-temp_hund) / 100, (-temp_hund) % 100);
                    } else {
                        printf("TEMP = %ld.%02ld C\n",
                            temp_hund / 100, temp_hund % 100);
                    }
                }
            } else if (*line == 'q') {
                printf("Restart by user request.\n");
                break;
            } else {
                printf("Unknown command: %s\n", line);
            }
        }
        Delay_Ms(100);
    }
    return 0;
}

void NMI_Handler(void) {}
void HardFault_Handler(void)
{
    while (1)
    {
    }
}
//#include <ch32v00x.h>
//#include <ch32v00x_usart.h>
#include <debug.h>
#include <stdlib.h>
#include <stdbool.h>
#include "ds18b20.h"
#include "gpio_helper.h"
#include "usart_io.h"

void NMI_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
void HardFault_Handler(void) __attribute__((interrupt("WCH-Interrupt-fast")));
/**
 * ほんの少しコードを整理。
 */
static const GpioPin RED_LED    =   { GPIOC, GPIO_Pin_1, 1 }; 
static const GpioPin YELLOW_LED =   { GPIOC, GPIO_Pin_2, 1 }; 
static const GpioPin GREEN_LED  =   { GPIOC, GPIO_Pin_3, 1 }; 
static const GpioPin PILOT_LED  =   { GPIOC, GPIO_Pin_4, 1 };
static const GpioPin BUTTON     =   { GPIOC, GPIO_Pin_5, 0 };

static int   dance_wait_ms      = 100;   // LEDダンスのウェイト時間（ミリ秒単位）この値は#=nで変更可能

// ActiveHighなLEDの定義。Port---LED---GNDという接続。gpio_write(&LED, 1)で点灯、gpio_write(&LED, 0)で消灯。
// ActiveLowにしたい場合は最後の値を0にして、Port---LED---VDDという接続にします。gpio_write(&LED, 1)で消灯、gpio_write(&LED, 0)で点灯になります。
//
// ActiveLowなボタンの定義。Port---BUTTON---GNDという接続。押されるとGNDに落ちて論理値1になります。
// ActiveHighにしたい場合は最後の値を1にします。この場合はPort---BUTTON---VDDという接続になります。押されるとVDDに繋がって論理値1になります。

void gpio_helper_init(){
    gpio_init(&RED_LED,       GPIO_DIR_OUT);
    gpio_init(&YELLOW_LED,    GPIO_DIR_OUT);
    gpio_init(&GREEN_LED,     GPIO_DIR_OUT);
    gpio_init(&PILOT_LED,     GPIO_DIR_OUT);
    gpio_init(&BUTTON,        GPIO_DIR_IN);
}
void system_initialize(){
    SystemCoreClockUpdate();
    Delay_Init();
    ds18b20_init();
    gpio_helper_init();
    //
    gpio_write(&PILOT_LED, 1);        // LED Turn-ON(to High)
    gpio_wait_on(&BUTTON, 3000);
    gpio_wait_off(&BUTTON, 0);
    gpio_write(&PILOT_LED, 0);
    //
    usart_io_init(115200);
    Delay_Ms(20);
    printf("Startup system clock: %lu Hz\n", SystemCoreClock);
}
ds18b20_rom_t system_startup(){
    ds18b20_rom_t rom;
    uint8_t  err;
    // ROM ID取得（起動時1回）
    err = ds18b20_read_rom(&rom);
    if (err != DS_OK) {
        printf("ROM read error: %d\r\n", err);
        while(1);
    }
    return rom;
}
/**
 * システム立ち上げ時のメッセージ表示。簡単な使い方と温度センサの情報を出力する
 */
void put_serial_startup_message(ds18b20_rom_t *rom){
    printf("Command: 'T' or 't' to read temperature.\n");
    printf("Command: 'R' to Red    LED ON, 'r' to Red    LED OFF.\n");
    printf("Command: 'Y' to Yellow LED ON, 'y' to Yellow LED OFF.\n");
    printf("Command: 'G' to Green  LED ON, 'g' to Green  LED OFF.\n");
    printf("Command: 'Q' or 'q' to quit and restart this program.\n");
    printf("ROM ID: %02X-%02X-%02X-%02X-%02X-%02X-%02X-%02X\n",
           rom->id[0], rom->id[1], rom->id[2], rom->id[3],
           rom->id[4], rom->id[5], rom->id[6], rom->id[7]);
}
/**
 * 温度センサの値をシリアルで上記に送る
 */
void put_serial_temperature(ds18b20_rom_t rom){
    int16_t  raw;
    int32_t  temp_hund;
    uint8_t  err;
    printf("Reading temperature on demand...\n");
    err = ds18b20_read_temp_raw(&rom, &raw);
    if (err == DS_OK) {
        printf("Raw temperature: %d (1LSB=1/16C)\n", raw);
    } else {
        printf("Temperature read error: %d\n", err);
        return;
    }
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
/**
 * LEDのダンスを表示する。'R'は赤LED点灯、'r'は赤LED消灯、'Y'は黄LED点灯、'y'は黄LED消灯、'G'は緑LED点灯、'g'は緑LED消灯。
 * '#'はミリ秒単位のウェイト。#=nでウェイトの値を変更できる。
 */
unsigned char *put_LED_dance(unsigned char *lptr){
    unsigned char c = *(lptr++);
    switch (c) {
        case '#':
            if (*lptr == '=') {
                lptr++;
                dance_wait_ms = atoi((const char *)lptr);
                printf("Dance wait time changed to %d ms\n", dance_wait_ms);
                while (isdigit(*lptr)) lptr++;
            } else {
                printf("Dance wait time  %d ms\n", dance_wait_ms);
                Delay_Ms(dance_wait_ms);
            }
            break;
        case 'R':
            gpio_write(&RED_LED, 1);
            printf("Red LED ON\n");
            break;
        case 'r':
            gpio_write(&RED_LED, 0);
            printf("Red LED OFF\n");
            break;
        case 'Y':
            gpio_write(&YELLOW_LED, 1);
            printf("Yellow LED ON\n");
            break;
        case 'y':
            gpio_write(&YELLOW_LED, 0);
            printf("Yellow LED OFF\n");
            break;
        case 'G':
            gpio_write(&GREEN_LED, 1);
            printf("Green LED ON\n");
            break;
        case 'g':
            gpio_write(&GREEN_LED, 0);
            printf("Green LED OFF\n");
            break;
        default:
            printf("Unknown command: %c\n", *lptr);
    }
    return lptr;
}
/**
 * メイン関数
 */
int main(void) {
    ds18b20_rom_t rom;
    int32_t  temp_hund;
    uint8_t  err;
    bool     loop_exit_request = false;
    system_initialize();
    rom = system_startup();
    put_serial_startup_message(&rom);
    while (!loop_exit_request) {
        if (usart_io_line_available()) {
            unsigned char line[128];
            unsigned int len;
            len =usart_io_read_line(line, sizeof(line));
            unsigned char *lptr = line;
            printf("Received: %s\n", lptr);
            while (lptr < (line + len)) {
                if (toupper(*lptr) == 'T') {
                    put_serial_temperature(rom);
                    lptr++;
                } else if (toupper(*lptr) == 'Q') {
                    printf("Restart by user request...\n");
                    loop_exit_request = true;
                    lptr++;
                 } else {
                    lptr = put_LED_dance(lptr);
                }
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
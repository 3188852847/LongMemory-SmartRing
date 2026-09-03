#include <cstdio>
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "decode.hpp"

namespace {
i2c_master_dev_handle_t device = nullptr;

axp::Reg read_register(uint8_t address) {
    uint8_t value = 0;
    // 发送的唯一字节是要读取的寄存器地址，不发送寄存器配置值。
    // 禁止在这里增加 write/update_bits 或调用厂商 PMIC 初始化函数。
    const auto error = i2c_master_transmit_receive(device, &address, 1, &value, 1, 200);
    if (error == ESP_OK) std::printf("reg[0x%02X]=0x%02X ", address, value);
    else std::printf("reg[0x%02X]=UNKNOWN(%s) ", address, esp_err_to_name(error));
    return {error == ESP_OK, value};
}

const char* yes_no(int value) {
    return value < 0 ? "UNKNOWN" : (value ? "yes" : "no");
}

void snapshot() {
    std::puts("\n--- AXP2101 snapshot (sequential reads, not atomic) ---");
    const auto id = read_register(0x03);
    // 0x4A 来自本机厂商 BSP 的识别逻辑；若不匹配，不盲目套用寄存器布局。
    if (!id.ok || id.value != 0x4A) {
        std::puts("\nChip identity unconfirmed; decoding skipped. No PMIC writes.");
        return;
    }
    const auto s1 = read_register(0x00);
    const auto s2 = read_register(0x01);
    const auto module = read_register(0x18);
    const auto detection = read_register(0x68);
    const auto adc = read_register(0x30);
    std::puts("");
    // 电压按照手册规定的高位、低位顺序读取。
    const auto high = read_register(0x34);
    const auto low = read_register(0x35);
    const auto ts_high = read_register(0x36);
    const auto gauge = read_register(0xA4);
    std::puts("");

    const int battery = axp::present(s1, detection);
    const int d = axp::direction(s2);
    const int s = axp::stage(s2);
    const char* directions[] = {"standby", "charging", "discharging"};
    const char* stages[] = {"trickle", "precharge", "constant_current", "constant_voltage",
                            "charge_done", "not_charging"};
    // 外部电源可供系统使用，但电池可能并未充电，因此不合并这两类状态。
    std::printf("vbus_good=%s battery_detection_enabled=%s battery_present=%s\n",
                yes_no(axp::bit(s1, 5)), yes_no(axp::bit(detection, 0)), yes_no(battery));
    std::printf("charger_enabled=%s gauge_enabled=%s vbat_adc_enabled=%s\n",
                yes_no(axp::bit(module, 1)), yes_no(axp::bit(module, 3)), yes_no(axp::bit(adc, 0)));
    std::printf("pmic_current_direction=%s pmic_charge_stage=%s\n",
                d < 0 ? "UNKNOWN" : directions[d], s < 0 ? "UNKNOWN" : stages[s]);
    std::printf("thermal_regulation=%s input_current_limit=%s vindpm=%s\n",
                yes_no(axp::bit(s1, 1)), yes_no(axp::bit(s1, 0)), yes_no(axp::bit(s2, 3)));
    const int mv = axp::millivolts(high, low, ts_high, adc, battery);
    if (mv < 0) std::puts("battery_mV=UNKNOWN (read/enable/presence/debug/zero check)");
    else std::printf("battery_mV=%d\n", mv);
    const int pct = axp::percent(gauge, module, battery);
    if (pct < 0) std::puts("battery_percent=UNKNOWN (read/enable/presence/range check)");
    else std::printf("battery_percent=%d (PMIC estimate; calibration not verified)\n", pct);
    std::puts("No charging parameters changed. This is not a Xiaozhi status capture.");
    std::fflush(stdout);
}
} // namespace

extern "C" void app_main() {
    std::puts("AXP2101 read-only diagnostic v1; USB Serial/JTAG; no display/audio/network.");
    // 独立程序仅配置 ESP32 I2C 引脚，不初始化 LCD、不操作 GPIO47 电源保持脚。
    i2c_master_bus_config_t config = {};
    config.i2c_port = I2C_NUM_0;
    config.sda_io_num = GPIO_NUM_8;
    config.scl_io_num = GPIO_NUM_9;
    config.clk_source = I2C_CLK_SRC_DEFAULT;
    config.glitch_ignore_cnt = 7;
    config.flags.enable_internal_pullup = true;
    i2c_master_bus_handle_t bus = nullptr;
    auto error = i2c_new_master_bus(&config, &bus);
    if (error != ESP_OK) {
        std::printf("I2C bus setup failed: %s\n", esp_err_to_name(error));
        return;
    }
    i2c_device_config_t target = {};
    target.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    target.device_address = 0x34;
    target.scl_speed_hz = 100000;
    error = i2c_master_bus_add_device(bus, &target, &device);
    if (error != ESP_OK) {
        std::printf("I2C device setup failed: %s\n", esp_err_to_name(error));
        i2c_del_master_bus(bus);
        return;
    }
    while (true) {
        snapshot();
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

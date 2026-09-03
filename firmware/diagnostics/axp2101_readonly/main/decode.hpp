#pragma once
#include <cstdint>

namespace axp {
// 未知值使用 -1，与真实的 0% 区分。此层不访问硬件，便于离线校验。
struct Reg { bool ok = false; uint8_t value = 0; };
constexpr int bit(Reg r, unsigned shift) {
    return r.ok ? ((r.value >> shift) & 1) : -1;
}
constexpr int present(Reg status, Reg detection) {
    return bit(detection, 0) == 1 ? bit(status, 3) : -1;
}
constexpr int direction(Reg status) {
    const int d = (status.value >> 5) & 3;
    return status.ok && d != 3 ? d : -1;
}
constexpr int stage(Reg status) {
    const int s = status.value & 7;
    return status.ok && s < 6 ? s : -1;
}
constexpr int percent(Reg raw, Reg module, int battery_present) {
    return raw.ok && bit(module, 3) == 1 && battery_present == 1 && raw.value <= 100
        ? raw.value : -1;
}
constexpr int millivolts(Reg high, Reg low, Reg ts_high, Reg adc, int battery_present) {
    // 手册要求先读高位再读低位；高位的两个调试控制位不是电压数据。
    // 不尝试改 ADC 配置。调试通道非默认时保守地不解释电压。
    if (!high.ok || !low.ok || !ts_high.ok || bit(adc, 0) != 1 || battery_present != 1
        || (high.value & 0xC0) || (ts_high.value & 0x40)) return -1;
    const int raw = ((high.value & 0x3F) << 8) | low.value;
    return raw > 0 ? raw : -1; // 1 mV/LSB；原始零值仍在日志中保留。
}
} // namespace axp

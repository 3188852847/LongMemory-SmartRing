#include "decode.hpp"
using axp::Reg;
constexpr Reg missing{};
constexpr Reg on{true, 0xFF};
constexpr Reg off{true, 0};

// 编译器执行的合成测试：不读串口，不连接设备，不能证明硬件测量正确。
static_assert(axp::bit(missing, 5) == -1);
static_assert(axp::bit(Reg{true, 0x20}, 5) == 1);
static_assert(axp::direction(Reg{true, 0x05}) == 0); // 有 USB 不等于电池充电
static_assert(axp::direction(Reg{true, 0x22}) == 1);
static_assert(axp::direction(Reg{true, 0x40}) == 2);
static_assert(axp::direction(Reg{true, 0x60}) == -1);
static_assert(axp::direction(missing) == -1);
static_assert(axp::stage(Reg{true, 0x24}) == 4);
static_assert(axp::stage(Reg{true, 0x25}) == 5);
static_assert(axp::stage(Reg{true, 6}) == -1);
static_assert(axp::stage(Reg{true, 7}) == -1);
static_assert(axp::stage(missing) == -1);
static_assert(axp::present(Reg{true, 8}, on) == 1);
static_assert(axp::present(off, on) == 0);
static_assert(axp::present(on, off) == -1);
static_assert(axp::present(missing, on) == -1);
static_assert(axp::percent(off, on, 1) == 0); // 真实零与读取失败不能混淆
static_assert(axp::percent(Reg{true, 100}, on, 1) == 100);
static_assert(axp::percent(Reg{true, 101}, on, 1) == -1);
static_assert(axp::percent(missing, on, 1) == -1);
static_assert(axp::percent(off, off, 1) == -1);
static_assert(axp::percent(off, on, 0) == -1);
static_assert(axp::percent(off, on, -1) == -1);
static_assert(axp::millivolts(Reg{true, 0x0E}, Reg{true, 0x74}, off, on, 1) == 3700);
static_assert(axp::millivolts(Reg{true, 0x4E}, Reg{true, 0x74}, off, on, 1) == -1);
static_assert(axp::millivolts(Reg{true, 0x0E}, Reg{true, 0x74}, Reg{true, 0x40}, on, 1) == -1);
static_assert(axp::millivolts(Reg{true, 0x0E}, missing, off, on, 1) == -1);
static_assert(axp::millivolts(Reg{true, 0x0E}, Reg{true, 0x74}, off, off, 1) == -1);
static_assert(axp::millivolts(Reg{true, 0x0E}, Reg{true, 0x74}, off, on, 0) == -1);
static_assert(axp::millivolts(off, off, off, on, 1) == -1);

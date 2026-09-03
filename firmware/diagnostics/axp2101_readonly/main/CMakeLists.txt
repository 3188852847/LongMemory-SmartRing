# 静态断言随固件编译检查；不是实机测试，也不增加运行期测试动作。
idf_component_register(
    SRCS "main.cpp" "${AXP_TEST_SOURCE}"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_i2c freertos
)

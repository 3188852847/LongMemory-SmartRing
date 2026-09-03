cmake_minimum_required(VERSION 3.16)
set(IDF_TARGET esp32s3)
# 只编译基础系统和本诊断的依赖，不加载厂商显示/电源初始化组件。
set(COMPONENTS main)
set(AXP_TEST_SOURCE "${CMAKE_CURRENT_LIST_DIR}/../../../tests/firmware/axp2101_decode_test.cpp"
    CACHE FILEPATH "Offline decoder assertions")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(axp2101_readonly)

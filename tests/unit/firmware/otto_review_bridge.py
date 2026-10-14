"""Stage the actual three display event handlers in a minimal host state harness."""
import argparse
import hashlib
import json
from pathlib import Path


def method(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end].replace(' override', '')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    board = args.source/'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc'
    text = board.read_text(encoding='utf-8')
    handlers = '\n'.join(method(text, signature) for signature in
                         ['void SetStatus(const char* status) override',
                          'void SetEmotion(const char* emotion) override',
                          'void SetServerEmotion(const char* emotion) override'])
    model = args.source/'main/boards/viewe-smartring-plus/otto_state.h'
    (args.output/'otto_state.h').write_bytes(model.read_bytes())
    harness = r'''
#include "otto_state.h"
#include <cassert>
#include <iostream>
uint32_t tick = 0;
uint32_t lv_tick_get() { return tick; }
namespace Lang { namespace Strings {
const char* STANDBY = "待机";
const char* CONNECTING = "连接中";
const char* LISTENING = "聆听中";
const char* SPEAKING = "说话中";
}}
namespace round_face { enum class Interaction { Idle, Listening, Speaking, Thinking, Error }; }
class LvglDisplay { public: void SetStatus(const char*) {} };
struct DisplayLockGuard { template<class T> explicit DisplayLockGuard(T*) {} };
class Bridge : public LvglDisplay {
public:
bool setup_ui_called_ = true;
round_face::Interaction interaction_ = round_face::Interaction::Idle;
otto::Model otto_state_;
std::string current_emotion_ = "neutral";
std::string visible;
void ApplyFace(const char*) { visible = otto_state_.Face(tick); }
// 宿主桩只去除 override：下面三个函数来自实际板级源码，未重新实现仲裁。
HANDLERS
};
int main() {
    Bridge display;
    display.SetStatus(Lang::Strings::LISTENING);
    display.SetEmotion("microphone");
    display.SetServerEmotion("happy");
    assert(display.visible == "neutral");
    display.SetStatus("思考中...");
    display.SetEmotion("thinking");
    assert(display.visible == "thinking");
    assert(display.otto_state_.emotion == "neutral");
    display.SetStatus(Lang::Strings::SPEAKING);
    assert(display.visible == "neutral"); // 无llm时不继承系统thinking。
    display.SetStatus(Lang::Strings::LISTENING);
    display.SetStatus("思考中...");
    display.SetEmotion("thinking");
    display.SetServerEmotion("happy");
    assert(display.visible == "thinking");
    display.SetStatus(Lang::Strings::SPEAKING);
    assert(display.visible == "happy");
    display.SetEmotion("thinking");
    assert(display.visible == "happy"); // 系统提示不改服务端情绪。
    tick = 100;
    display.SetStatus("已打断，请继续...");
    display.SetEmotion("microphone");
    display.SetServerEmotion("thinking");
    assert(display.visible == "surprised");
    assert(display.otto_state_.emotion == "neutral");
    tick = 750;
    display.SetEmotion("microphone");
    assert(display.visible == "neutral");
    display.SetEmotion("triangle_exclamation");
    display.SetServerEmotion("happy");
    assert(display.visible == "confused");
    display.SetStatus(Lang::Strings::CONNECTING);
    display.SetEmotion("neutral");
    assert(display.visible == "neutral");
    display.SetEmotion("cloud_slash");
    assert(display.visible == "sad");
    display.SetStatus(Lang::Strings::STANDBY); // 正常音频关闭实际传入此状态。
    display.SetEmotion("neutral");
    assert(display.visible == "neutral");
    display.SetStatus(Lang::Strings::SPEAKING); // 主动TTS没有前置STT。
    display.SetServerEmotion("not-an-emotion");
    assert(display.visible == "neutral");
    std::cout << "PASS actual SetStatus/SetEmotion/SetServerEmotion call sequences\n";
}
'''.replace('HANDLERS', handlers)
    (args.output/'bridge_test.cc').write_text(harness, encoding='utf-8')
    record = {str(board): hashlib.sha256(text.encode()).hexdigest(),
              str(model): hashlib.sha256(model.read_text(encoding='utf-8').encode()).hexdigest()}
    (args.output/'source-fingerprints.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    # 仅宿主MSVC，所有输出位于自己树；不调用ESP构建或设备工具。
    build = "$ErrorActionPreference = 'Stop'\n. 'D:\\01-开发环境\\03-C-C++\\scripts\\Enter-Cpp.ps1'\n"
    build += f"& cl.exe /nologo /std:c++17 /EHsc /utf-8 '{args.output/'bridge_test.cc'}' '/Fe:{args.output/'bridge_test.exe'}' '/Fo:{args.output/'bridge_test.obj'}'\n"
    build += "if ($LASTEXITCODE -ne 0) { throw 'Host bridge compile failed' }\n"
    build += f"& '{args.output/'bridge_test.exe'}'\n"
    build += "if ($LASTEXITCODE -ne 0) { throw 'Host bridge test failed' }\n"
    (args.output/'run.ps1').write_text(build, encoding='utf-8-sig')
    print(str(args.output/'run.ps1'))


if __name__ == '__main__':
    main()

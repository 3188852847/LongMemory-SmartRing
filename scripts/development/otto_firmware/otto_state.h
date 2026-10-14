#pragma once
#include <cstdint>
#include <cstring>
#include <string>

// 只仲裁显示，真实采集/连接/播放仍由 Application 决定。
namespace otto {
inline constexpr const char* kNames[] = {"angry", "confident", "confused", "cool", "crying",
        "delicious", "embarrassed", "funny", "happy", "kissy", "laughing", "loving",
        "neutral", "relaxed", "sad", "shocked", "silly", "sleepy", "surprised",
        "thinking", "winking"};
inline const char* Normalize(const char* name) {
    if (name) for (auto item : kNames) if (std::strcmp(name, item) == 0) return item;
    return "neutral";
}
inline unsigned FaceIndex(const char* name) {
    for (unsigned i = 0; i < 21; ++i) if (std::strcmp(name, kNames[i]) == 0) return i;
    return 12; // neutral
}
struct RetryGate {
    uint32_t failed_mask = 0;
    uint32_t failed_at[22]{};
    bool CanTry(unsigned index, uint32_t now) const {
        return !(failed_mask & (1u << index)) || uint32_t(now - failed_at[index]) >= 1000;
    }
    void Fail(unsigned index, uint32_t now) {
        failed_mask |= 1u << index;
        failed_at[index] = now;
    }
};
enum class State { Idle, Connecting, Listening, Thinking, Speaking, Error, Disconnected };
struct Model {
    State state = State::Idle;
    std::string emotion = "neutral";
    uint32_t interrupted_at = 0;
    bool interrupted = false;
    void Transition(State next, uint32_t now, bool interrupt = false) {
        state = next;
        interrupted = interrupt && next == State::Listening;
        interrupted_at = now;
        if (next != State::Speaking && next != State::Thinking) emotion = "neutral";
    }
    void Emotion(const char* name) {
        // 协议没有 turnID：本轮思考/播放之外的 emotion 均不进入缓存。
        if (state == State::Thinking || state == State::Speaking) emotion = Normalize(name);
    }
    void SystemEmotion(const char* name, uint32_t now) {
        if (!name) return;
        if (std::strcmp(name, "triangle_exclamation") == 0) Transition(State::Error, now);
        else if (std::strcmp(name, "cloud_slash") == 0 || std::strcmp(name, "wifi_off") == 0)
            Transition(State::Disconnected, now);
        // thinking/speaking/microphone 是系统表现提示，绝不进入服务端情绪缓存。
    }
    const char* Face(uint32_t now) const {
        if (state == State::Error) return "confused";
        if (state == State::Disconnected) return "sad";
        if (state == State::Thinking) return "thinking";
        if (state == State::Speaking) return emotion.c_str();
        // 650ms 只控制提示脸，既不等待一轮 GIF，也不延迟原采集逻辑。
        if (interrupted && uint32_t(now - interrupted_at) < 650) return "surprised";
        return "neutral";
    }
};
}  // namespace otto

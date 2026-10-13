#pragma once

// 纯几何动画模型：不访问音频、设备、存储或网络，可在电脑上独立验证。
// Interaction 来自真实状态事件；Emotion 来自已有服务消息，两者分别组合。
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace round_face {
enum class Interaction { Idle, Listening, Thinking, Speaking, Error };
enum class Emotion { Neutral, Happy, Concerned };
struct Shape {
    float eye_width = 28.f;
    float eye_height = 36.f;
    float mouth_width = 36.f;
};
struct Pose {
    float eye_width = 28.f, eye_height = 36.f;
    float mouth_width = 36.f, mouth_height = 8.f;
    float gaze_x = 0.f, gaze_y = 0.f, mouth_y = 38.f;
    float blink = 0.f;
    // 色彩插值也使用 dt，而不是每帧固定混色。
    uint8_t color_mix = 255;
};

class Motion {
public:
    static constexpr uint32_t kFramePeriodMs = 40;
    Pose Step(uint32_t now, Interaction interaction, Emotion emotion, Shape shape,
              bool reduced_motion = false) {
        if (!initialized_) {
            initialized_ = true;
            last_ = now;
            next_blink_ = now + 2700;
            next_gaze_ = now + 3600;
            current_.eye_width = shape.eye_width;
            current_.eye_height = shape.eye_height;
            current_.mouth_width = shape.mouth_width;
        }
        const uint32_t elapsed = std::min<uint32_t>(now - last_, 100);
        last_ = now;
        const float dt = elapsed / 1000.f;
        const float blend = reduced_motion ? 1.f : 1.f - std::exp(-dt / .16f);
        Pose target;
        target.eye_width = shape.eye_width;
        target.eye_height = shape.eye_height;
        target.mouth_width = shape.mouth_width;
        const bool active = !reduced_motion && interaction != Interaction::Error;
        const float breath = active ? std::sin((now % 4400) / 4400.f * kTau) : 0.f;

        // 固定种子的局部伪随机只用于待机细节，绝不随机切换情绪。
        if (active && interaction == Interaction::Idle && Due(now, next_gaze_)) {
            gaze_target_ = static_cast<float>(static_cast<int>(Random() % 9) - 4);
            next_gaze_ = now + 2400 + Random() % 3600;
        }
        target.gaze_x = interaction == Interaction::Idle && active ? gaze_target_ : 0.f;
        target.gaze_y = breath * .9f;
        target.mouth_y = 38.f + breath * .7f;
        if (interaction == Interaction::Listening) {
            target.eye_height = std::min(48.f, shape.eye_height + 5.f);
            target.mouth_width = shape.mouth_width * .8f;
            target.mouth_height = 6.f;
            target.gaze_y = -1.f + breath * .4f;
        } else if (interaction == Interaction::Thinking) {
            target.eye_width = std::max(12.f, shape.eye_width - 5.f);
            target.eye_height = std::max(16.f, shape.eye_height * .62f);
            target.gaze_x = reduced_motion ? 0.f : 5.f;
            target.gaze_y = reduced_motion ? -2.f : -4.f + breath * .6f;
        } else if (interaction == Interaction::Speaking) {
            // 这是“正在说话”的示意动作，不读取振幅，也不声称口型同步。
            const float a = active ? std::sin((now % 420) / 420.f * kTau) : 0.f;
            const float b = active ? std::sin((now % 710) / 710.f * kTau) : 0.f;
            target.mouth_width = std::min(64.f, shape.mouth_width + 8.f);
            target.mouth_height = active ? 10.f + 8.f * std::abs(.7f * a + .3f * b) : 12.f;
        } else if (interaction == Interaction::Error) {
            target.eye_height = std::max(16.f, shape.eye_height * .7f);
            target.mouth_width = 20.f;
            target.mouth_height = 18.f;
            target.gaze_x = target.gaze_y = 0.f;
        }
        if (interaction != Interaction::Error && emotion == Emotion::Happy) {
            target.eye_height *= .82f;
            target.mouth_width = std::min(64.f, target.mouth_width + 10.f);
            target.mouth_height += 3.f;
        } else if (interaction != Interaction::Error && emotion == Emotion::Concerned) {
            target.eye_height *= .9f;
            target.mouth_width *= .85f;
        }
        float closure = 0.f;
        if (active) {
            if (!blinking_ && Due(now, next_blink_)) {
                blinking_ = true;
                blink_started_ = now;
            }
            if (blinking_) {
                const uint32_t age = now - blink_started_;
                if (age >= 220) {
                    blinking_ = false;
                    next_blink_ = now + 2200 + Random() % 3800;
                } else {
                    // 先闭后开，连续包络；卡顿不会把眼睛永久留在闭合态。
                    const float phase = age < 80 ? age / 80.f : (220 - age) / 140.f;
                    closure = phase * phase * (3.f - 2.f * phase);
                }
            }
        } else {
            blinking_ = false;
            next_blink_ = now + 2700;
        }
        current_.eye_width += (target.eye_width - current_.eye_width) * blend;
        current_.eye_height += (target.eye_height - current_.eye_height) * blend;
        current_.mouth_width += (target.mouth_width - current_.mouth_width) * blend;
        current_.mouth_height += (target.mouth_height - current_.mouth_height) * blend;
        current_.gaze_x += (target.gaze_x - current_.gaze_x) * blend;
        current_.gaze_y += (target.gaze_y - current_.gaze_y) * blend;
        current_.mouth_y += (target.mouth_y - current_.mouth_y) * blend;
        Pose result = current_;
        result.eye_height = std::max(4.f, result.eye_height * (1.f - .9f * closure));
        result.blink = closure;
        result.color_mix = static_cast<uint8_t>(std::max(1.f, blend * 255.f));
        return result;
    }
private:
    static constexpr float kTau = 6.28318530718f;
    static bool Due(uint32_t now, uint32_t deadline) {
        return static_cast<int32_t>(now - deadline) >= 0;
    }
    uint32_t Random() {
        random_ = random_ * 1664525u + 1013904223u;
        return random_;
    }
    bool initialized_ = false, blinking_ = false;
    uint32_t last_ = 0, next_blink_ = 0, blink_started_ = 0, next_gaze_ = 0;
    uint32_t random_ = 0x57a3u;
    float gaze_target_ = 0.f;
    Pose current_;
};
}  // namespace round_face

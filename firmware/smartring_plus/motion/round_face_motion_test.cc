#include "round_face_motion.h"
#include <cassert>
#include <cmath>
#include <iostream>

using namespace round_face;

int main() {
    Motion idle;
    float minimum_eye = 99.f, maximum_blink = 0.f;
    for (uint32_t ms = 0; ms < 20000; ms += 40) {
        auto pose = idle.Step(ms, Interaction::Idle, Emotion::Neutral, {});
        assert(std::isfinite(pose.eye_height));
        assert(pose.eye_height >= 4.f && pose.eye_height <= 48.f);
        minimum_eye = std::min(minimum_eye, pose.eye_height);
        maximum_blink = std::max(maximum_blink, pose.blink);
    }
    assert(minimum_eye < 8.f && maximum_blink > .9f);
    Motion normal, happy;
    Pose a, b;
    for (uint32_t ms = 0; ms < 1500; ms += 40) {
        a = normal.Step(ms, Interaction::Speaking, Emotion::Neutral, {});
        b = happy.Step(ms, Interaction::Speaking, Emotion::Happy, {});
    }
    assert(b.mouth_width > a.mouth_width && b.eye_height < a.eye_height);
    float speaking = a.mouth_height;
    a = normal.Step(1520, Interaction::Listening, Emotion::Neutral, {});
    assert(std::abs(a.mouth_height - speaking) < 3.f);  // 打断从当前形状重定向。
    for (uint32_t ms = 1560; ms < 2600; ms += 40)
        a = normal.Step(ms, Interaction::Listening, Emotion::Neutral, {});
    assert(a.mouth_height < 6.1f && a.eye_height > 40.f);
    Motion error;
    for (uint32_t ms = 0; ms < 1600; ms += 40)
        a = error.Step(ms, Interaction::Error, Emotion::Happy, {});
    assert(std::abs(a.mouth_width - 20.f) < .01f && a.blink == 0.f);
    assert(a.gaze_x == 0.f && a.gaze_y == 0.f);
    Motion slow, fast;
    slow.Step(0, Interaction::Listening, Emotion::Neutral, {});
    fast.Step(0, Interaction::Listening, Emotion::Neutral, {});
    for (uint32_t ms = 40; ms <= 800; ms += 40)
        a = slow.Step(ms, Interaction::Listening, Emotion::Neutral, {});
    for (uint32_t ms = 20; ms <= 800; ms += 20)
        b = fast.Step(ms, Interaction::Listening, Emotion::Neutral, {});
    assert(std::abs(a.eye_height - b.eye_height) < .01f);
    Motion wrap;
    wrap.Step(0xfffffff0u, Interaction::Idle, Emotion::Neutral, {});
    a = wrap.Step(24, Interaction::Listening, Emotion::Neutral, {});
    assert(a.eye_height > 36.f && std::isfinite(a.gaze_y));
    a = wrap.Step(10000, Interaction::Speaking, Emotion::Happy, {}, true);
    assert(a.blink == 0.f && a.gaze_x == 0.f);
    std::cout << "round face model: blink, state/emotion composition, interruption, error, dt, wrap, reduced motion passed\n";
}

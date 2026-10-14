#include "otto_state.h"
#include <cassert>
#include <cstring>
#include <iostream>
int main() {
    otto::Model m;
    auto face = [&](const char* value, uint32_t now) { assert(std::strcmp(m.Face(now), value) == 0); };
    face("neutral", 0);
    m.Emotion("happy"); face("neutral", 1);
    m.Transition(otto::State::Listening, 10); m.Emotion("angry"); face("neutral", 11);
    m.Transition(otto::State::Thinking, 20); m.Emotion("happy"); face("thinking", 21);
    m.Transition(otto::State::Speaking, 30); face("happy", 30);
    m.Emotion("invalid"); face("neutral", 31);
    m.Emotion("sad"); face("sad", 32);
    m.Transition(otto::State::Listening, 40, true); m.Emotion("angry");
    face("surprised", 40); face("surprised", 689); face("neutral", 690);
    m.Transition(otto::State::Thinking, 700); m.Transition(otto::State::Speaking, 710); face("neutral", 710);
    m.Transition(otto::State::Error, 720); m.Emotion("happy"); face("confused", 721);
    m.Transition(otto::State::Disconnected, 730); face("sad", 731);
    m.Transition(otto::State::Idle, 740); face("neutral", 740);
    m.Transition(otto::State::Speaking, 750); face("neutral", 750); // proactive turn
    m.Transition(otto::State::Idle, 760); face("neutral", 760); // manual tts.stop branch
    m.Transition(otto::State::Listening, 0xfffffff0, true);
    face("surprised", 0x20); face("neutral", 0x290); // tick wrap
    std::cout << "Otto state arbitration: passed\n";
}

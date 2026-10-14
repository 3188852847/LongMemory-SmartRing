"""Apply the audited 0014 display adaptation to an exclusively assigned copy."""
from pathlib import Path
import argparse
import shutil

def replace(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)

def adapt(root):
    board = root / 'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc'
    text = board.read_text(encoding='utf-8')
    text = replace(text, '#include "round_face_motion.h"', '#include "round_face_motion.h"\n#include "otto_state.h"')
    text = replace(text, '    std::string current_emotion_ = "neutral";', '''    std::string current_emotion_ = "neutral";
    otto::Model otto_state_;
    bool wallpaper_view_ = false;  // 仅运行时选择，不写 NVS。
    std::string active_gif_;
    std::string active_face_;
    std::string attempted_face_;
    uint32_t attempted_at_ = 0;
    otto::RetryGate retry_gate_;

    void ClearGif() {
        // 先解除 LVGL 对解码画布的引用，再释放唯一控制器。
        if (wallpaper_image_) lv_image_set_src(wallpaper_image_, nullptr);
        wallpaper_gif_.reset();
        wallpaper_source_.reset();
        wallpaper_ready_ = false;
        active_gif_.clear();
        active_face_.clear();
    }

    bool ShowOtto(const char* emotion) {
        const char* normalized = otto::Normalize(emotion);
        const unsigned index = otto::FaceIndex(normalized);
        if (!retry_gate_.CanTry(index, lv_tick_get())) return false;
        if (wallpaper_ready_ && active_face_ == normalized &&
            wallpaper_gif_ && !wallpaper_gif_->HasDecodeError()) return true;
        const std::string key = std::string("otto_") + normalized + ".gif";
        void* data = nullptr;
        size_t size = 0;
        if (!Assets::GetInstance().GetAssetData(key, data, size)) return false;
        // 固定、已校验资源才交给厂商无长度参数的 GIF 解码器。
        if (size < 13 || std::memcmp(data, "GIF89a", 6) != 0) return false;
        ClearGif();
        auto source = std::make_unique<LvglRawImage>(data, size);
        auto controller = std::make_unique<LvglGif>(source->image_dsc());
        if (!controller->IsLoaded() || controller->width() != 240 || controller->height() != 240) {
            retry_gate_.Fail(index, lv_tick_get());
            return false;
        }
        if (!wallpaper_image_) {
            wallpaper_image_ = lv_image_create(container_);
            lv_obj_clear_flag(wallpaper_image_, LV_OBJ_FLAG_CLICKABLE);
        }
        lv_obj_set_size(wallpaper_image_, 240, 240);
        lv_obj_center(wallpaper_image_);
        lv_obj_remove_flag(wallpaper_image_, LV_OBJ_FLAG_HIDDEN);
        wallpaper_source_ = std::move(source);
        wallpaper_gif_ = std::move(controller);
        active_gif_ = key;
        active_face_ = normalized;
        wallpaper_ready_ = true;
        wallpaper_gif_->SetFrameCallback([this]() {
            if (wallpaper_image_ && wallpaper_gif_)
                lv_image_set_src(wallpaper_image_, wallpaper_gif_->image_dsc());
        });
        wallpaper_gif_->SetLoopCount(0);
        lv_image_set_src(wallpaper_image_, wallpaper_gif_->image_dsc());
        wallpaper_gif_->Start();
        return true;
    }''')
    text = replace(text, '\n        wallpaper_image_ = lv_image_create(container_);', '\n        if (!wallpaper_image_) wallpaper_image_ = lv_image_create(container_);')
    text = replace(text, '        if (face_timer_ != nullptr) lv_timer_pause(face_timer_);', '        active_gif_ = "wallpaper";')
    text = replace(text, '        lv_obj_set_size(wallpaper_image_, width_, height_);\n        lv_obj_center(wallpaper_image_);', '        lv_obj_set_size(wallpaper_image_, width_, height_);\n        lv_obj_center(wallpaper_image_);\n        lv_obj_remove_flag(wallpaper_image_, LV_OBJ_FLAG_HIDDEN);')
    text = replace(text, '        if (wallpaper_ready_ || container_ == nullptr) {', '        if ((wallpaper_ready_ && active_gif_ == "wallpaper") || container_ == nullptr || !retry_gate_.CanTry(21, lv_tick_get())) {')
    # 该行在原壁纸方法中唯一；ShowOtto 的缩进不同，避免影响新分支。
    text = replace(text, '\n        auto controller = std::make_unique<LvglGif>(source->image_dsc());\n        if (!controller->IsLoaded() || controller->width() != width_', '\n        ClearGif();\n        auto controller = std::make_unique<LvglGif>(source->image_dsc());\n        if (!controller->IsLoaded() || controller->width() != width_')
    text = replace(text, '            ESP_LOGE(TAG, "Round wallpaper must decode to %dx%d", width_, height_);', '            retry_gate_.Fail(21, lv_tick_get());\n            ESP_LOGE(TAG, "Round wallpaper must decode to %dx%d", width_, height_);')
    text = replace(text, '        const char* value = emotion == nullptr ? "neutral" : emotion;', '''        // 解码器回调只标记错误；另一个显示仲裁回调安全释放，不在自身回调删除自身。
        if (wallpaper_gif_ && wallpaper_gif_->HasDecodeError()) {
            retry_gate_.Fail(active_gif_ == "wallpaper" ? 21 : otto::FaceIndex(active_face_.c_str()), lv_tick_get());
            ClearGif();
            attempted_face_.clear();
        }
        if (!wallpaper_view_) {
            const char* face = otto_state_.Face(lv_tick_get());
            const uint32_t now = lv_tick_get();
            if (attempted_face_ != face || uint32_t(now - attempted_at_) >= 1000) {
                attempted_face_ = face;
                attempted_at_ = now;
                if (!ShowOtto(face) && !ShowOtto("neutral")) {
                    TryLoadWallpaper();  // Otto 缺失/解码失败：原壁纸，再到原几何脸。
                    if (!wallpaper_ready_ && wallpaper_image_)
                        lv_obj_add_flag(wallpaper_image_, LV_OBJ_FLAG_HIDDEN);
                }
            }
        } else {
            TryLoadWallpaper();
            if (!wallpaper_ready_) ShowOtto("neutral");
        }
        const char* value = emotion == nullptr ? "neutral" : emotion;''')
    text = replace(text, '        if (wallpaper_ready_) lv_timer_pause(face_timer_);', '        // 保留轻量仲裁定时器，及时结束插话提示；不分配逐帧图片。')
    text = text.replace('        TryLoadWallpaper();\n        ApplySkinStyles();', '        ApplySkinStyles();')
    text = replace(text, '            interaction_ = round_face::Interaction::Idle;\n            current_emotion_ = "neutral";', '''            interaction_ = round_face::Interaction::Idle;
            current_emotion_ = "neutral";
            otto_state_.Transition(std::strcmp(status, Lang::Strings::CONNECTING) == 0 ?
                otto::State::Connecting : otto::State::Idle, lv_tick_get());''')
    text = replace(text, '            interaction_ = round_face::Interaction::Listening;', '''            interaction_ = round_face::Interaction::Listening;
            otto_state_.Transition(otto::State::Listening, lv_tick_get(),
                std::strcmp(status, "已打断，请继续...") == 0);''')
    text = replace(text, '            interaction_ = round_face::Interaction::Speaking;', '            interaction_ = round_face::Interaction::Speaking;\n            otto_state_.Transition(otto::State::Speaking, lv_tick_get());')
    text = replace(text, '            interaction_ = round_face::Interaction::Thinking;', '            interaction_ = round_face::Interaction::Thinking;\n            otto_state_.Transition(otto::State::Thinking, lv_tick_get());')
    start = text.index('        if (value == "microphone") interaction_')
    end = text.index('        ApplyFace(current_emotion_.c_str());', start)
    text = text[:start] + '''        if (value == "microphone") {
            interaction_ = round_face::Interaction::Listening;
        } else if (value == "triangle_exclamation" || value == "cloud_slash" || value == "wifi_off") {
            interaction_ = round_face::Interaction::Error;
        }
        otto_state_.SystemEmotion(value.c_str(), lv_tick_get());
        current_emotion_ = otto_state_.emotion;
''' + text[end:]
    text = replace(text, '    RoundSkinConfig GetRoundSkin() const {', '''    void SetServerEmotion(const char* emotion) override {
        if (!setup_ui_called_) return;
        DisplayLockGuard lock(this);
        otto_state_.Emotion(emotion);
        current_emotion_ = otto_state_.emotion;
        ApplyFace(current_emotion_.c_str());
    }

    bool SetFaceView(const std::string& view) {
        if (view != "otto" && view != "wallpaper") throw std::invalid_argument("Unknown face view");
        DisplayLockGuard lock(this);
        wallpaper_view_ = view == "wallpaper";
        ClearGif();
        attempted_face_.clear();
        if (wallpaper_image_) lv_obj_add_flag(wallpaper_image_, LV_OBJ_FLAG_HIDDEN);
        ApplyFace(current_emotion_.c_str());
        if (wallpaper_view_ && (active_gif_ != "wallpaper" || !wallpaper_image_ ||
            lv_obj_has_flag(wallpaper_image_, LV_OBJ_FLAG_HIDDEN))) {
            wallpaper_view_ = false;
            ApplyFace(current_emotion_.c_str());
            return false;
        }
        return true;
    }

    RoundSkinConfig GetRoundSkin() const {''')
    text = replace(text, '    void InitializeRoundWallpaperTools() {\n        auto& mcp = McpServer::GetInstance();', '''    void InitializeRoundWallpaperTools() {
        auto& mcp = McpServer::GetInstance();
        mcp.AddUserOnlyTool("self.screen.set_round_face_view",
            "Select otto or retained wallpaper for this boot only; no NVS changes",
            PropertyList({Property("view", kPropertyTypeString)}),
            [this](const PropertyList& properties) -> ReturnValue {
                return static_cast<SmartRingFaceDisplay*>(display_)->SetFaceView(
                    properties["view"].value<std::string>());
            });''')
    # 更新注释反映新优先级，不改原壁纸读写与皮肤配置逻辑。
    text = text.replace('// 通知和字幕。动态壁纸存在时，它是所有日常交互状态的角色主视觉；\n// 几何脸只在壁纸缺失或无法解码时作为固件内置回退。', '// 通知和字幕。默认 Otto，原壁纸可运行时选择；缺资源时逐级回退。')
    board.write_text(text, encoding='utf-8', newline='\n')
    shutil.copyfile(Path(__file__).with_name('otto_state.h'), board.with_name('otto_state.h'))
    app = root / 'main/application.cc'
    text = app.read_text(encoding='utf-8')
    text = replace(text, 'Schedule([display, message = std::string(text->valuestring)]() {\n                    display->SetChatMessage("user", message.c_str());', 'Schedule([this, display, message = std::string(text->valuestring)]() {\n#if CONFIG_BOARD_TYPE_VIEWE_SMARTRING_PLUS\n                    if (GetDeviceState() != kDeviceStateListening) return;\n#endif\n                    display->SetChatMessage("user", message.c_str());')
    text = replace(text, 'display->SetEmotion(emotion_str.c_str());', 'display->SetServerEmotion(emotion_str.c_str());')
    app.write_text(text, encoding='utf-8', newline='\n')
    display = root / 'main/display/display.h'
    text = display.read_text(encoding='utf-8')
    text = replace(text, '    virtual void SetEmotion(const char* emotion);', '''    virtual void SetEmotion(const char* emotion);
    // 服务端情绪与系统提示分开，原板型默认兼容既有 SetEmotion。
    virtual void SetServerEmotion(const char* emotion) { SetEmotion(emotion); }''')
    display.write_text(text, encoding='utf-8', newline='\n')
    gif = root / 'main/display/lvgl_display/gif/lvgl_gif.cc'
    text = gif.read_text(encoding='utf-8')
    text = replace(text, 'playing_(false), loaded_(false),', 'playing_(false), loaded_(false), decode_error_(false),')
    text = replace(text, '    // Render first frame\n    if (gif_->canvas) {', '''    // 先解码真实第一帧，切换立即可见；不把未初始化的索引画布当图像。
    if (gd_get_frame(gif_) != 1) {
        decode_error_ = true;
        Cleanup();
        return;
    }
    // Render first frame
    if (gif_->canvas) {''')
    text = replace(text, '    if (has_next == 0) {', '''    if (has_next < 0) {
        decode_error_ = true;
        playing_ = false;
        if (timer_) lv_timer_pause(timer_);
        ESP_LOGE(TAG, "GIF frame decode failed");
        return;
    }
    if (has_next == 0) {''')
    gif.write_text(text, encoding='utf-8', newline='\n')
    gif_header = gif.with_suffix('.h')
    text = gif_header.read_text(encoding='utf-8')
    text = replace(text, '    bool IsLoaded() const;', '    bool IsLoaded() const;\n    bool HasDecodeError() const { return decode_error_; }')
    text = replace(text, '    bool loaded_;', '    bool loaded_;\n    bool decode_error_;')
    gif_header.write_text(text, encoding='utf-8', newline='\n')
    cmake = root / 'CMakeLists.txt'
    text = cmake.read_text(encoding='utf-8')
    text = replace(text, 'set(PROJECT_VER "2.2.3")', 'set(PROJECT_VER "2.2.3-otto0014")')
    cmake.write_text(text, encoding='utf-8', newline='\n')

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('source', type=Path)
    adapt(p.parse_args().source)

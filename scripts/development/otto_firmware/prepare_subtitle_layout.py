"""从已核验0015复制到全新ASCII目录，只生成板级字幕修复及审计补丁。"""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil


BOARD = "main/boards/viewe-smartring-plus/viewe-smartring-plus.cc"
BASELINE_HASHES = {
    BOARD: "ddc0401177cd020d4a21afeecf40e627cfaea7c02a45870764afed49066c9d47",
    "CMakeLists.txt": "b3e2212c8a3f7f7d5fbf9ac55879e0a81dd3b25a9ddb05257f7b03296cb4ad14",
    "main/application.cc": "d7fd88fa50803a98611388bbafed829bc074b5dd43851443bea8129d5aecf366",
}

OLD_LAYOUT = """        // 字幕最多占中央安全区下方两行，不再堆叠历史聊天气泡。
        if (bottom_bar_ != nullptr && chat_message_label_ != nullptr) {
            lv_obj_set_size(bottom_bar_, 272, 58);
            lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_TRANSP, 0);
            lv_obj_align(bottom_bar_, LV_ALIGN_BOTTOM_MID, 0, -38);
            lv_obj_set_width(chat_message_label_, 252);
            lv_obj_set_height(chat_message_label_, 48);
            lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_DOT);
            lv_obj_set_style_text_align(chat_message_label_, LV_TEXT_ALIGN_CENTER, 0);
        }
"""

SUBTITLE_LAYOUT = """    void ApplySubtitleLayout() {
        if (bottom_bar_ == nullptr || chat_message_label_ == nullptr) return;
        // 360圆屏：文字矩形(70,252)-(290,306)的最远角半径167.3 < 180。
        // 固定20号字实际行高25；两行加2px行距需52px，54px不能沿用旧48px。
        lv_obj_set_size(bottom_bar_, 224, 58);
        lv_obj_set_style_pad_all(bottom_bar_, 0, 0);
        lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_TRANSP, 0);
        lv_obj_align(bottom_bar_, LV_ALIGN_BOTTOM_MID, 0, -52);
        lv_obj_set_style_pad_all(chat_message_label_, 0, 0);
        lv_obj_set_size(chat_message_label_, 220, 54);
        lv_obj_set_style_text_line_space(chat_message_label_, 2, 0);
        lv_obj_set_style_text_letter_space(chat_message_label_, 0, 0);
        static const lv_anim_t subtitle_animation = [] {
            lv_anim_t animation;
            lv_anim_init(&animation);
            lv_anim_set_delay(&animation, 900);
            lv_anim_set_reverse_delay(&animation, 1200);
            lv_anim_set_repeat_delay(&animation, 1200);
            lv_anim_set_repeat_count(&animation, LV_ANIM_REPEAT_INFINITE);
            return animation;
        }();
        lv_obj_set_style_anim(chat_message_label_, &subtitle_animation, 0);
        lv_obj_set_style_anim_duration(chat_message_label_, lv_anim_speed_clamped(24, 300, 60000), 0);
        lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_SCROLL);
        lv_obj_set_style_text_align(chat_message_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(chat_message_label_, LV_ALIGN_CENTER, 0, 0);
    }

"""

CHAT_OVERRIDE = """    void SetChatMessage(const char* role, const char* content) override {
        // esp_lvgl_port使用递归互斥量；覆盖通用更新和板级恢复的整个原子显示过程。
        DisplayLockGuard lock(this);
        const std::string wrapped = WrapSubtitle(content);
        LcdDisplay::SetChatMessage(role, content == nullptr ? nullptr : wrapped.c_str());
        if (!setup_ui_called_) return;
        // 通用多行消费者会重设底部对齐；恢复安全区并从头启动新字幕滚动。
        // 不改隐藏语义或音频状态；长文本在同一显示框内完整往返，不使用省略号。
        ApplySubtitleLayout();
    }

"""

WRAP_SUBTITLE = """    static size_t SubtitleClusterBytes(const char* text) {
        auto read = [](const char* p, uint32_t& cp) -> size_t {
            const auto first = static_cast<unsigned char>(p[0]);
            size_t count = first < 0x80 ? 1 : first >= 0xC2 && first < 0xE0 ? 2 :
                           first >= 0xE0 && first < 0xF0 ? 3 : first >= 0xF0 && first < 0xF5 ? 4 : 1;
            cp = first & (count == 1 ? 0xFF : count == 2 ? 0x1F : count == 3 ? 0x0F : 0x07);
            for (size_t i = 1; i < count; ++i) {
                const auto next = static_cast<unsigned char>(p[i]);
                if (next == 0 || (next & 0xC0) != 0x80) { cp = first; return 1; }
                cp = (cp << 6) | (next & 0x3F);
            }
            return count;
        };
        uint32_t first;
        size_t bytes = read(text, first);
        bool joined = false;
        bool regional = first >= 0x1F1E6 && first <= 0x1F1FF;
        while (text[bytes] != '\\0') {
            uint32_t cp;
            const size_t next = read(text + bytes, cp);
            // 保留常用组合音标、变体选择符、肤色及ZWJ序列；不在UTF-8字节间断行。
            const bool combining = (cp >= 0x0300 && cp <= 0x036F) ||
                (cp >= 0x1AB0 && cp <= 0x1AFF) || (cp >= 0x1DC0 && cp <= 0x1DFF) ||
                (cp >= 0x20D0 && cp <= 0x20FF) || (cp >= 0xFE20 && cp <= 0xFE2F) ||
                (cp >= 0xFE00 && cp <= 0xFE0F) || (cp >= 0xE0100 && cp <= 0xE01EF) ||
                (cp >= 0x1F3FB && cp <= 0x1F3FF);
            const bool pair = regional && cp >= 0x1F1E6 && cp <= 0x1F1FF;
            if (!combining && cp != 0x200D && !joined && !pair) break;
            bytes += next;
            joined = cp == 0x200D;
            if (pair) regional = false;
        }
        return bytes;
    }

    std::string WrapSubtitle(const char* content) const {
        if (content == nullptr || chat_message_label_ == nullptr) return content ? content : "";
        const lv_font_t* font = lv_obj_get_style_text_font(chat_message_label_, LV_PART_MAIN);
        std::string result;
        std::string line;
        // SCROLL模式默认不自动折行；按实际LVGL字形宽度增加换行，不截断UTF-8。
        // 每次测量仅限当前行，长段不会反复测量已经输出的整份正文。
        for (size_t i = 0; content[i] != '\\0';) {
            const size_t bytes = SubtitleClusterBytes(content + i);
            if (content[i] == '\\n' || content[i] == '\\r') {
                result.append(content + i, bytes);
                line.clear();
            } else {
                std::string candidate = line;
                candidate.append(content + i, bytes);
                lv_point_t size;
                lv_text_get_size(&size, candidate.c_str(), font, 0, 2,
                                 LV_COORD_MAX, LV_TEXT_FLAG_EXPAND);
                if (!line.empty() && size.x > 220) {
                    result += '\\n';
                    line.clear();
                }
                result.append(content + i, bytes);
                line.append(content + i, bytes);
            }
            i += bytes;
        }
        return result;
    }

"""


def change_board(text):
    if text.count(OLD_LAYOUT) != 1:
        raise ValueError("0015_subtitle_layout_mismatch")
    anchor = "    void ApplySkinStyles() {"
    if text.count(anchor) != 1:
        raise ValueError("0015_skin_anchor_mismatch")
    text = text.replace(anchor, WRAP_SUBTITLE + SUBTITLE_LAYOUT + anchor, 1)
    text = text.replace(OLD_LAYOUT, "        ApplySubtitleLayout();\n", 1)
    anchor = "    void SetTheme(Theme* theme) override {"
    if text.count(anchor) != 1:
        raise ValueError("0015_theme_anchor_mismatch")
    text = text.replace(anchor, CHAT_OVERRIDE + anchor, 1)
    theme = "        DisplayLockGuard lock(this);\n        ApplySkinStyles();\n    }\n\n    void SetStatus"
    if text.count(theme) != 1:
        raise ValueError("0015_theme_restore_mismatch")
    return text.replace(theme, "        DisplayLockGuard lock(this);\n        ApplySkinStyles();\n        ApplySubtitleLayout();\n    }\n\n    void SetStatus", 1)


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def prepare(baseline, output, patch, evidence):
    baseline, output = baseline.resolve(), output.resolve()
    if output.exists() or patch.exists() or evidence.exists():
        raise ValueError("output_must_be_new")
    if not str(output).isascii() or " " in str(output) or output == baseline or output.is_relative_to(baseline):
        raise ValueError("isolated_ascii_output_required")
    for relative, expected in BASELINE_HASHES.items():
        if sha(baseline / relative) != expected:
            raise ValueError("0015_baseline_hash_mismatch:" + relative)
    paths = list(baseline.rglob("*"))
    if any(file.is_symlink() or file.is_junction() for file in paths):
        raise ValueError("source_links_not_allowed")
    # 源码及已有受管组件复制到独占目录；不复制任何旧build或日志，不建联接。
    before = {str(p.relative_to(baseline)).replace("\\", "/"): sha(p)
              for p in paths if p.is_file() and not p.name.endswith(".log")}
    if any(p.is_dir() and p.parent == baseline and p.name.startswith("build") for p in paths):
        raise ValueError("unexpected_build_in_source")
    shutil.copytree(baseline, output, ignore=shutil.ignore_patterns("*.log"))
    changes = {BOARD: change_board((baseline / BOARD).read_text(encoding="utf-8")),
               "CMakeLists.txt": (baseline / "CMakeLists.txt").read_text(encoding="utf-8").replace('"2.2.3-otto0015"', '"2.2.3-otto0016"')}
    diff = []
    for relative, text in changes.items():
        original = (baseline / relative).read_text(encoding="utf-8")
        (output / relative).write_text(text, encoding="utf-8", newline="\n")
        diff.extend(difflib.unified_diff(original.splitlines(keepends=True), text.splitlines(keepends=True),
                                       fromfile="a/" + relative, tofile="b/" + relative))
    after = {relative: sha(output / relative) for relative in before}
    changed = sorted(p for p in before if before[p] != after[p])
    if changed != sorted(changes):
        raise ValueError("unexpected_source_change")
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text("".join(diff), encoding="utf-8", newline="\n")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"baseline": str(baseline), "output": str(output),
        "version": "2.2.3-otto0016", "changed": changed, "before": before, "after": after,
        "patch_sha256": sha(patch), "external_original_edited": False,
        "serial_opened": False, "device_written": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.baseline, args.output, args.patch, args.evidence)

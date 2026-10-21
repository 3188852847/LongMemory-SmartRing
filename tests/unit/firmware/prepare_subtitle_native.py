"""显式固定源码输入，使用其真实LVGL和Puhui字形离线验证字幕消费者；不连接设备。"""
import argparse
from pathlib import Path
import re


CONF = """#ifndef LV_CONF_H
#define LV_CONF_H
#define LV_COLOR_DEPTH 16
#define LV_USE_OS LV_OS_NONE
#define LV_MEM_SIZE (4 * 1024 * 1024)
#define LV_USE_LOG 0
#define LV_FONT_FMT_TXT_LARGE 1
#define LV_USE_FONT_COMPRESSED 1
#define LV_USE_DRAW_SW 1
#define LV_USE_LABEL 1
#define LV_USE_THEME_DEFAULT 0
#define LV_USE_THEME_SIMPLE 0
#define LV_USE_THEME_MONO 0
#define LV_USE_FLEX 0
#define LV_USE_GRID 0
"""

CMAKE = """cmake_minimum_required(VERSION 3.24)
project(subtitle_consumer LANGUAGES C CXX)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
add_compile_options($<$<C_COMPILER_ID:MSVC>:/utf-8>)
add_subdirectory("@SOURCE@/managed_components/lvgl__lvgl" lvgl)
add_executable(subtitle_consumer consumer.cc "@SOURCE@/managed_components/78__xiaozhi-fonts/src/font_puhui_20_4.c")
target_link_libraries(subtitle_consumer PRIVATE lvgl)
"""

HARNESS = r'''#include <lvgl.h>
#include "src/widgets/label/lv_label_private.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#undef assert
#define assert(condition) do { if(!(condition)) { std::cerr<<"consumer assertion: " #condition " line "<<__LINE__<<std::endl; std::exit(2); } } while(0)
extern "C" { LV_FONT_DECLARE(font_puhui_20_4); }
static std::vector<uint16_t> frame(360*360), pixels(360*360);
static void flush(lv_display_t* display,const lv_area_t* area,uint8_t* data) {
    assert(area->x1==0&&area->y1==0&&area->x2==359&&area->y2==359);
    std::memcpy(frame.data(),data,frame.size()*2);
    lv_display_flush_ready(display);
}
static void snapshot(const std::filesystem::path& file) {
    // 计时器的刷新周期可能长于一次虚拟tick；截帧前显式提交当前失效区域。
    lv_refr_now(lv_display_get_default());
    std::ofstream out(file,std::ios::binary);out<<"P6\n360 360\n255\n";
    for(int y=0;y<360;y++)for(int x=0;x<360;x++) {
        const uint16_t p=frame[y*360+x];
        unsigned char rgb[3]={static_cast<unsigned char>(((p>>11)&31)*255/31),
            static_cast<unsigned char>(((p>>5)&63)*255/63),static_cast<unsigned char>((p&31)*255/31)};
        if(std::hypot(x-179.5,y-179.5)>179.5)rgb[0]=rgb[1]=rgb[2]=32;
        out.write(reinterpret_cast<char*>(rgb),3);
    }
}
// 单线程头less夹具的锁是空操作。实际固件的递归锁另核对固定esp_lvgl_port源码。
struct DisplayLockGuard {explicit DisplayLockGuard(void*){}};
struct LcdDisplay {
    lv_obj_t* bottom_bar_;
    lv_obj_t* chat_message_label_;
    bool setup_ui_called_=true,hide_subtitle_=false;
    LcdDisplay() {
        auto* screen=lv_screen_active();
        bottom_bar_=lv_obj_create(screen);
        lv_obj_set_size(bottom_bar_,272,58);
        lv_obj_set_style_pad_all(bottom_bar_,8,0);
        lv_obj_set_style_border_width(bottom_bar_,0,0);
        lv_obj_set_style_radius(bottom_bar_,0,0);
        lv_obj_set_style_bg_opa(bottom_bar_,LV_OPA_TRANSP,0);
        lv_obj_set_style_text_font(bottom_bar_,&font_puhui_20_4,0);
        lv_obj_set_style_text_color(bottom_bar_,lv_color_hex(0xC8C8C8),0);
        chat_message_label_=lv_label_create(bottom_bar_);
        lv_obj_set_size(chat_message_label_,252,48);
        lv_obj_align(chat_message_label_,LV_ALIGN_CENTER,0,0);
        lv_label_set_long_mode(chat_message_label_,LV_LABEL_LONG_DOT);
        lv_obj_set_style_text_align(chat_message_label_,LV_TEXT_ALIGN_CENTER,0);
    }
    virtual ~LcdDisplay(){lv_obj_delete(bottom_bar_);}
    // 与0015实际非微信消费者相同的正文/隐藏/多行重定位路径，保留被覆盖的底部复位。
    virtual void SetChatMessage(const char*,const char* content) {
        lv_label_set_text(chat_message_label_,content);
        if(content==nullptr||content[0]=='\0'||hide_subtitle_)lv_obj_add_flag(bottom_bar_,LV_OBJ_FLAG_HIDDEN);
        else lv_obj_remove_flag(bottom_bar_,LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(bottom_bar_,LV_ALIGN_BOTTOM_MID,0,0);
    }
};
struct FixedDisplay: LcdDisplay {
@METHODS@
@OVERRIDE@
};
static std::string without_newlines(const std::string& s) {
    std::string out;for(char c:s)if(c!='\n'&&c!='\r')out+=c;return out;
}
static bool inside(const lv_area_t& area,double margin) {
    for(int x:{area.x1,area.x2})for(int y:{area.y1,area.y2})
        if(std::hypot(x-179.5,y-179.5)>179.5-margin)return false;
    return true;
}
static void tick(int ms=20){lv_tick_inc(ms);lv_timer_handler();}
int wmain(int argc,wchar_t**argv) {
    assert(argc==2);std::filesystem::path output(argv[1]);std::filesystem::create_directories(output);
    lv_init();auto* display=lv_display_create(360,360);
    lv_display_set_color_format(display,LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display,pixels.data(),nullptr,pixels.size()*2,LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display,flush);
    lv_obj_set_style_bg_color(lv_screen_active(),lv_color_hex(0),0);
    lv_obj_set_style_bg_opa(lv_screen_active(),LV_OPA_COVER,0);
    const std::vector<std::pair<std::string,std::string>> cases={
      {"short",u8"我在听，请继续。"},
      {"punctuation",u8"今天先处理最重要的事情，接着休息一下；然后再决定后面的安排。"},
      {"five_sentences",u8"第一句话，我们先一起把今天最重要的事情说清楚。第二句话，也记得给自己留下一点安静休息的时间。第三句话，如果遇到困难可以慢慢讨论，不必一次解决所有问题。第四句话，等你准备好了，我们再安排接下来要做的事情。第五句话，今天的进度已经很好，可以安心收尾。"},
      {"original_newlines",u8"第一行。\n第二行，保留原有换行。\n第三行结束。"},
      {"latin_clusters",u8"Hello cafe\u0301! A\u0308 BCDEFGHIJKLMNOPQRSTUVWXYZ; family: \U0001F469\u200D\U0001F4BB, flag: \U0001F1E8\U0001F1F3."},
    };
    {
      LcdDisplay old;old.SetChatMessage("assistant",cases[2].second.c_str());lv_obj_update_layout(old.bottom_bar_);
      lv_area_t box;lv_obj_get_coords(old.chat_message_label_,&box);assert(!inside(box,0));
      tick();snapshot(output/"0015-clipped.ppm");
      std::cout<<"old_box "<<box.x1<<' '<<box.y1<<' '<<box.x2<<' '<<box.y2<<'\n';
    }
    FixedDisplay fixed;fixed.ApplySubtitleLayout();
    // 独立40ms刷新与共享LVGL计时器：模拟Otto旁路对象更新，不替代真实GIF解码验收。
    auto* sibling=lv_obj_create(lv_screen_active());
    lv_obj_set_size(sibling,8,8);lv_obj_align(sibling,LV_ALIGN_CENTER,0,-40);
    lv_timer_create([](lv_timer_t* timer){auto* object=static_cast<lv_obj_t*>(lv_timer_get_user_data(timer));
      lv_obj_set_style_bg_color(object,lv_color_hex(lv_tick_get()&0xffffff),0);
      lv_obj_align(object,LV_ALIGN_CENTER,int(lv_tick_get()/40%3),-40);
    },40,sibling);
    for(const auto& item:cases) {
      fixed.SetChatMessage("assistant",item.second.c_str());lv_obj_update_layout(fixed.bottom_bar_);
      const std::string wrapped=lv_label_get_text(fixed.chat_message_label_);
      assert(without_newlines(wrapped)==without_newlines(item.second));
      assert(wrapped.find("e\n\xCC\x81")==std::string::npos);
      assert(wrapped.find("\xE2\x80\x8D\n")==std::string::npos);
      auto* label=reinterpret_cast<lv_label_t*>(fixed.chat_message_label_);
      assert(label->offset.x==0&&label->offset.y==0);
      lv_area_t box,parent;lv_obj_get_coords(fixed.chat_message_label_,&box);lv_obj_get_coords(fixed.bottom_bar_,&parent);
      assert(inside(box,8)&&inside(parent,8));
      std::vector<std::string> lines;size_t start=0;
      while(start<wrapped.size()){auto end=wrapped.find('\n',start);if(end==std::string::npos)end=wrapped.size();lines.push_back(wrapped.substr(start,end-start));start=end+1;}
      std::vector<bool> seen(lines.size(),false);
      for(const auto& line:lines){lv_point_t size;lv_text_get_size(&size,line.c_str(),&font_puhui_20_4,0,2,LV_COORD_MAX,LV_TEXT_FLAG_EXPAND);assert(size.x<=220);}
      tick();snapshot(output/(item.first+"-start.ppm"));
      bool all=false;int elapsed=0;bool moving=false;int first_move=-1;
      for(;elapsed<=65000&&!all;elapsed+=20) {
        if(elapsed<=800)assert(label->offset.y==0);
        if(label->offset.y<0&&first_move<0)first_move=elapsed;
        for(size_t i=0;i<lines.size();i++){
          int y=static_cast<int>(i)*27+label->offset.y;
          if(y>=0&&y+25<=54&&!seen[i]) {
              seen[i]=true;
              std::cout<<item.first<<" first_visible_line="<<i<<" offset_y="<<label->offset.y<<" at="<<elapsed<<'\n';
              if(i+1==lines.size())snapshot(output/(item.first+"-last-visible.ppm"));
          }
        }
        all=true;for(bool visible:seen)all=all&&visible;
        moving=moving||label->offset.y<0;
        if(all)break;
        tick();if(elapsed==2000)snapshot(output/(item.first+"-middle.ppm"));
      }
      assert(all);if(lines.size()>2){assert(moving);assert(first_move>=800);}
      snapshot(output/(item.first+"-tail.ppm"));
      assert(lv_label_get_text(fixed.chat_message_label_)==wrapped);
      std::cout<<item.first<<" lines="<<lines.size()<<" every_line_visible=true scan_ms="<<elapsed<<" first_move_ms="<<first_move<<" face_sibling_timer_ms=40 offset_y="<<label->offset.y<<" bytes="<<wrapped.size()<<" box="<<box.x1<<','<<box.y1<<','<<box.x2<<','<<box.y2<<'\n';
    }
    fixed.SetChatMessage("assistant",u8"新的短字幕。");lv_obj_update_layout(fixed.bottom_bar_);
    auto* label=reinterpret_cast<lv_label_t*>(fixed.chat_message_label_);assert(label->offset.x==0&&label->offset.y==0);
    fixed.SetChatMessage("assistant","");assert(lv_obj_has_flag(fixed.bottom_bar_,LV_OBJ_FLAG_HIDDEN));
    fixed.hide_subtitle_=true;fixed.SetChatMessage("assistant",u8"按既有设置隐藏。");assert(lv_obj_has_flag(fixed.bottom_bar_,LV_OBJ_FLAG_HIDDEN));
    std::cout<<"reset_and_hidden_semantics=true\n";
    return 0;
}
'''


def prepare(source, output):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError("native_output_must_be_new")
    board = (source / "main/boards/viewe-smartring-plus/viewe-smartring-plus.cc").read_text(encoding="utf-8")
    methods = board[board.index("    static size_t SubtitleClusterBytes"):board.index("    void ApplySkinStyles()")]
    override = board[board.index("    void SetChatMessage(const char* role"):board.index("    void SetTheme(Theme* theme) override")]
    output.mkdir(parents=True)
    template = (source / "managed_components/lvgl__lvgl/lv_conf_template.h").read_text(encoding="utf-8")
    widget_section = template[template.index("#define LV_USE_ANIMIMG"):template.index("#define LV_USE_THEME_DEFAULT")]
    widgets = set(re.findall(r"#define\s+(LV_USE_\w+)\s+", widget_section)) - {"LV_USE_LABEL"}
    conf = CONF + "".join(f"#define {name} 0\n" for name in sorted(widgets)) + "#endif\n"
    (output / "lv_conf.h").write_text(conf, encoding="utf-8")
    (output / "CMakeLists.txt").write_text(CMAKE.replace("@SOURCE@", source.as_posix()), encoding="utf-8")
    (output / "consumer.cc").write_text(HARNESS.replace("@METHODS@", methods).replace("@OVERRIDE@", override), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)

"""O: execute actual board appearance/setup/theme methods with N's GIF harness.

MSVC and LVGL object stubs run offline; this is not panel/render/device evidence.
The base LCD stub deliberately installs a white theme image and black labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from otto_review_bridge import method


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fixed-gifs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    subprocess.run([sys.executable, '-B', str(here/'otto_review_display.py'),
                    '--source', str(args.source), '--fixed-gifs', str(args.fixed_gifs),
                    '--scaffolding', str(here/'gif_host'), '--output', str(args.output)], check=True)
    board = args.source/'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc'
    text = board.read_text(encoding='utf-8')
    harness = (args.output/'bridge_test.cc').read_text(encoding='utf-8')
    header = args.output/'lvgl.h'
    stub = header.read_text(encoding='utf-8')
    stub = stub.replace('typedef struct { const void* src; int flags, w, h; } lv_obj_t;', r'''
typedef uint32_t lv_color_t;
#define LV_OPA_TRANSP 0
#define LV_OPA_50 127
#define LV_OPA_COVER 255
#define LV_ALIGN_CENTER 0
#define LV_ALIGN_BOTTOM_MID 1
#define LV_RADIUS_CIRCLE 180
#define LV_LABEL_LONG_DOT 0
#define LV_TEXT_ALIGN_CENTER 0
typedef struct lv_obj_t lv_obj_t;
struct lv_obj_t { const void* src; int flags,w,h; lv_obj_t* parent;
    uint32_t bg, text; int opa; const void* bg_image; int x,y; };
static inline lv_color_t lv_color_hex(uint32_t v){return v;}
static inline lv_obj_t* lv_obj_get_screen(lv_obj_t*o){while(o->parent)o=o->parent;return o;}
static inline void lv_obj_set_style_bg_color(lv_obj_t*o,uint32_t v,int part){o->bg=v;}
static inline void lv_obj_set_style_text_color(lv_obj_t*o,uint32_t v,int part){o->text=v;}
static inline void lv_obj_set_style_bg_opa(lv_obj_t*o,int v,int part){o->opa=v;}
static inline void lv_obj_set_style_bg_image_src(lv_obj_t*o,const void*v,int part){o->bg_image=v;}
static inline void lv_obj_set_style_border_width(lv_obj_t*o,int v,int part){}
static inline void lv_obj_set_style_pad_all(lv_obj_t*o,int v,int part){}
static inline void lv_obj_set_style_radius(lv_obj_t*o,int v,int part){}
static inline void lv_obj_set_style_text_align(lv_obj_t*o,int v,int part){}
static inline void lv_obj_set_width(lv_obj_t*o,int v){o->w=v;}
static inline void lv_obj_set_height(lv_obj_t*o,int v){o->h=v;}
static inline void lv_obj_align(lv_obj_t*o,int align,int x,int y){o->x=x;o->y=y;}
static inline void lv_label_set_long_mode(lv_obj_t*o,int mode){}
static inline lv_obj_t* lv_obj_create(lv_obj_t*p){auto*o=(lv_obj_t*)calloc(1,sizeof(lv_obj_t));o->parent=p;return o;}
''')
    stub = stub.replace('(void)parent; return (lv_obj_t*)calloc(1,sizeof(lv_obj_t));',
                        'lv_obj_t* o=(lv_obj_t*)calloc(1,sizeof(lv_obj_t));o->parent=parent;return o;')
    # The C decoder also includes this header; use a C-compatible creator.
    stub = stub.replace('auto*o=(lv_obj_t*)', 'lv_obj_t*o=(lv_obj_t*)')
    stub = stub.replace('static inline void lv_timer_reset',
                        'static inline void lv_timer_set_repeat_count(lv_timer_t*t,int count){}\nstatic inline void lv_timer_reset')
    header.write_text(stub, encoding='utf-8')
    harness = harness.replace('enum class Interaction { Idle,Listening,Thinking,Speaking,Error };',
                              'enum class Interaction { Idle,Listening,Thinking,Speaking,Error }; struct Motion {static constexpr int kFramePeriodMs=40;};')
    start = harness.index('class DisplayFixture:')
    harness = harness[:start] + r'''
struct Theme { virtual ~Theme()=default; };
struct ThemeImage { const void* image_dsc(){return this;} };
struct LvglTheme:Theme { ThemeImage image; bool with_image=true;
    ThemeImage* background_image(){return with_image?&image:nullptr;} };
struct RoundSkinConfig { uint32_t background=0xFFFFFF,foreground=0,muted=0x222222; };
struct BaseLcd:LvglDisplay {
    lv_obj_t root{},container{},top{},bottom{},status{},note{},chat{},network{},battery{},mute{},box{},emoji{},image{};
    lv_obj_t*container_=&container,*top_bar_=&top,*bottom_bar_=&bottom;
    lv_obj_t*status_label_=&status,*notification_label_=&note,*chat_message_label_=&chat;
    lv_obj_t*network_label_=&network,*battery_label_=&battery,*mute_label_=&mute;
    lv_obj_t*emoji_box_=&box,*emoji_label_=&emoji,*emoji_image_=&image;
    Theme*current_theme_=nullptr;
    bool setup_ui_called_=false;
    LvglTheme light;
    BaseLcd(){current_theme_=&light;for(auto*o:{&container,&top,&bottom,&box})o->parent=&root;}
    void SetupUI(){setup_ui_called_=true;ThemePaint();}
    void SetTheme(Theme*t){current_theme_=t;if(setup_ui_called_)ThemePaint();}
    void ThemePaint(){
        // Model the actual base LCD writes; hostile light theme tests board reapplication.
        for(auto*o:{&root,&container,&top,&bottom,&box}){
            o->bg=0xFFFFFF;o->opa=127;o->bg_image=&light.image;o->text=0;
        }
        for(auto*o:{&status,&note,&chat,&network,&battery,&mute,&emoji})o->text=0;
    }
};
using LcdDisplay=BaseLcd;
''' + harness[start:]
    harness = harness.replace('class DisplayFixture:public LvglDisplay', 'class DisplayFixture:public BaseLcd')
    harness = harness.replace('    lv_obj_t root{};\n    lv_obj_t*container_=&root,*left_eye_=&root,*right_eye_=&root,*mouth_=&root;',
                              '    lv_obj_t eye1{},eye2{},lip{};\n    lv_obj_t*left_eye_=&eye1,*right_eye_=&eye2,*mouth_=&lip;')
    harness = harness.replace('wallpaper_view_=false,setup_ui_called_=true;', 'wallpaper_view_=false;')
    harness = harness.replace('    int width_=360,height_=360;', r'''
    bool view_styles_initialized_=false,otto_view_styles_=false;
    RoundSkinConfig skin_;
    lv_timer_t*face_timer_=nullptr;
    DisplayFixture(){setup_ui_called_=true;}
    static void FaceTimerCallback(lv_timer_t*){}
    int width_=360,height_=360;''')
    harness = harness.replace('~DisplayFixture(){ClearGif();free(wallpaper_image_);}',
                              '~DisplayFixture(){ClearGif();free(wallpaper_image_);if(face_timer_){lv_timer_delete(face_timer_);free(left_eye_);free(right_eye_);free(mouth_);}}')
    methods = '\n'.join(method(text, signature) for signature in [
        'void ApplyViewStyles(bool force = false)', 'void ApplySkinStyles()',
        'static void ConfigureFacePart(lv_obj_t* object)', 'void SetupUI() override',
        'void SetTheme(Theme* theme) override'])
    harness = harness.replace('    static constexpr const char* kWallpaperAssetName=', methods+'\n    static constexpr const char* kWallpaperAssetName=')
    extra = r'''
    auto Black=[](DisplayFixture&d){
        for(auto*o:{&d.root,d.container_,d.top_bar_,d.bottom_bar_}){
            assert(o->bg==0 && o->bg_image==nullptr);
            assert(o->opa==(o==d.bottom_bar_?LV_OPA_TRANSP:LV_OPA_COVER));
        }
        assert(d.emoji_box_->opa==LV_OPA_TRANSP&&d.emoji_box_->bg_image==nullptr);
        for(auto*o:{d.status_label_,d.notification_label_,d.emoji_label_})assert(o->text==0xFFFFFF);
        for(auto*o:{d.chat_message_label_,d.network_label_,d.battery_label_,d.mute_label_})assert(o->text==0xC8C8C8);
        assert(d.skin_.background==0xFFFFFF&&d.skin_.foreground==0&&d.skin_.muted==0x222222);
    };
    Load();files["round_wallpaper.gif"]=wallpaper;
    {
        DisplayFixture d;
        d.setup_ui_called_=false;
        d.SetTheme(&d.light); // theme before setup must not require real UI objects.
        d.SetupUI();Black(d); // actual board setup, actual appearance method, real GIF decoder.
        assert(d.bottom_bar_->w==272&&d.bottom_bar_->h==58&&d.bottom_bar_->y==-38);
        assert(d.chat_message_label_->w==252&&d.chat_message_label_->h==48);
        auto SavedSkin=d.skin_;
        for(int i=0;i<30;i++){
            d.SetTheme(&d.light);Black(d); // explicit light + background image resets.
            for(auto*s:{Lang::Strings::CONNECTING,Lang::Strings::STANDBY,Lang::Strings::LISTENING,"思考中...",Lang::Strings::SPEAKING,"已打断，请继续..."}){
                d.SetStatus(s);Black(d);
            }
            for(auto*s:{"microphone","thinking","triangle_exclamation","cloud_slash","wifi_off","neutral"}){d.SetEmotion(s);Black(d);}
            for(auto*s:{"happy","sad","angry","thinking","neutral"}){d.SetServerEmotion(s);Black(d);}
            d.ApplySkinStyles();Black(d); // old white skin explicitly reapplied.
            assert(d.SetFaceView("wallpaper"));
            assert(d.container_->bg==SavedSkin.background&&d.root.bg==SavedSkin.background);
            assert(d.container_->bg_image==d.light.background_image()->image_dsc());
            assert(d.container_->opa==255&&d.top_bar_->opa==127&&d.bottom_bar_->opa==0);
            assert(d.status_label_->text==SavedSkin.foreground&&d.mute_label_->text==SavedSkin.muted);
            assert(d.wallpaper_image_->w==360&&!lv_obj_has_flag(d.wallpaper_image_,LV_OBJ_FLAG_HIDDEN));
            d.SetTheme(&d.light);assert(d.container_->bg_image==d.light.background_image()->image_dsc());
            assert(d.SetFaceView("otto"));Black(d);
            assert(d.wallpaper_image_->w==240&&!lv_obj_has_flag(d.wallpaper_image_,LV_OBJ_FLAG_HIDDEN));
        }
        files.erase("round_wallpaper.gif");assert(!d.SetFaceView("wallpaper"));Black(d);
        d.light.with_image=false;
        files["round_wallpaper.gif"]=wallpaper;assert(d.SetFaceView("wallpaper"));
        d.SetTheme(&d.light);assert(d.container_->bg_image==nullptr&&d.container_->bg==SavedSkin.background);
        assert(d.SetFaceView("otto"));Black(d);
    }
    assert(timers.empty()&&tracked_live()==0);
    std::cout<<"PASS O: actual SetupUI/SetTheme/ApplyViewStyles; light/image/white-skin/state/icon contrast; 30 wallpaper round trips; original GIF lifecycle checks\n";
'''
    harness = harness.replace('    std::cout<<', extra+'\n    std::cout<<', 1)
    (args.output/'bridge_test.cc').write_text(harness, encoding='utf-8')
    record = json.loads((args.output/'source-fingerprints.json').read_text(encoding='utf-8'))
    record['board_raw_sha256'] = hashlib.sha256(board.read_bytes()).hexdigest()
    record['test_generator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    upstream = json.loads((here.parents[2]/'scripts/development/otto_firmware/upstream.json').read_text(encoding='utf-8'))
    resource_hashes = {}
    for item in upstream['files']:
        if not item['path'].startswith('gifs/'):
            continue
        data = (args.fixed_gifs/Path(item['path']).name).read_bytes()
        assert len(data) == item['bytes']
        blob = f'blob {len(data)}\0'.encode() + data
        assert hashlib.sha1(blob).hexdigest() == item['git_blob_sha1']
        (args.output/Path(item['path']).name).write_bytes(data)
        resource_hashes[Path(item['path']).name] = hashlib.sha256(data).hexdigest()
    assert len(resource_hashes) == 21
    all_faces = r'''
    for(auto*name:otto::kNames)files[std::string("otto_")+name+".gif"]=Read((std::string(name)+".gif").c_str());
    {
        DisplayFixture d;
        d.SetStatus(Lang::Strings::SPEAKING);
        for(auto*name:otto::kNames){
            d.SetServerEmotion(name);Black(d);
            assert(d.active_face_==name&&d.wallpaper_image_->w==240);
        }
    }
    assert(timers.empty()&&tracked_live()==0);
'''
    harness = harness.replace('    std::cout<<"PASS O:', all_faces+'\n    std::cout<<"PASS O:')
    (args.output/'bridge_test.cc').write_text(harness, encoding='utf-8')
    record['all_21_fixed_gifs_sha256'] = resource_hashes
    (args.output/'source-fingerprints.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    print('Actual board appearance/setup/theme methods staged; base LCD and LVGL are explicit stubs.')


if __name__ == '__main__':
    main()

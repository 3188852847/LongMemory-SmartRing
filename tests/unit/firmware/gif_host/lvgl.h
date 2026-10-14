#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
#include <limits.h>
#define LV_GIF_CACHE_DECODE_DATA 0
#define LV_USE_DRAW_SW_ASM 0
#define LV_DRAW_SW_ASM_HELIUM 2
#define LV_FS_SEEK_CUR 1
#define LV_FS_SEEK_SET 0
#define LV_FS_MODE_RD 1
#define LV_FS_RES_OK 0
typedef struct { int unused; } lv_fs_file_t;
typedef int lv_fs_res_t;
#ifdef __cplusplus
extern "C" {
#endif
void* tracked_malloc(size_t n);
void* tracked_realloc(void* p, size_t n);
void tracked_free(void* p);
size_t tracked_live(void);
size_t tracked_peak(void);
#ifdef __cplusplus
}
#endif
#define lv_malloc tracked_malloc
#define lv_realloc tracked_realloc
#define lv_free tracked_free
static inline int lv_fs_open(lv_fs_file_t* a, const void* b, int c) { return -1; }
static inline int lv_fs_read(lv_fs_file_t* a,void* b,size_t c,void* d) { assert(0); return -1; }
static inline int lv_fs_seek(lv_fs_file_t* a,size_t b,int c) { assert(0); return -1; }
static inline int lv_fs_tell(lv_fs_file_t* a,uint32_t* b) { assert(0); return -1; }
static inline int lv_fs_close(lv_fs_file_t* a) { assert(0); return -1; }
#define LV_IMAGE_HEADER_MAGIC 0x19
#define LV_IMAGE_FLAGS_MODIFIABLE 1
#define LV_COLOR_FORMAT_ARGB8888 1
#define LV_COLOR_FORMAT_RAW_ALPHA 2
#define LV_OBJ_FLAG_CLICKABLE 1
#define LV_OBJ_FLAG_HIDDEN 2
#define LV_SCROLLBAR_MODE_OFF 0
typedef struct { uint32_t magic, flags, cf, w, h, stride; } lv_image_header_t;
typedef struct { lv_image_header_t header; uint32_t data_size; const uint8_t* data; } lv_img_dsc_t;
typedef struct { const void* src; int flags, w, h; } lv_obj_t;
typedef struct lv_timer_t lv_timer_t;
struct lv_timer_t { void (*callback)(lv_timer_t*); void* user; int paused; };
#ifdef __cplusplus
extern "C" {
#endif
uint32_t lv_tick_get(void);
uint32_t lv_tick_elaps(uint32_t start);
lv_timer_t* lv_timer_create(void (*cb)(lv_timer_t*), int period, void* user);
void lv_timer_delete(lv_timer_t* t);
static inline void* lv_timer_get_user_data(lv_timer_t* t) { return t->user; }
static inline void lv_timer_pause(lv_timer_t* t) { t->paused=1; }
static inline void lv_timer_resume(lv_timer_t* t) { t->paused=0; }
static inline void lv_timer_reset(lv_timer_t* t) { (void)t; }
#ifdef __cplusplus
}
#endif
static inline lv_obj_t* lv_image_create(lv_obj_t* parent) { (void)parent; return (lv_obj_t*)calloc(1,sizeof(lv_obj_t)); }
static inline void lv_image_set_src(lv_obj_t* obj,const void* src) { obj->src=src; }
static inline void lv_obj_clear_flag(lv_obj_t* o,int f) { o->flags&=~f; }
static inline void lv_obj_remove_flag(lv_obj_t* o,int f) { o->flags&=~f; }
static inline void lv_obj_add_flag(lv_obj_t* o,int f) { o->flags|=f; }
static inline int lv_obj_has_flag(lv_obj_t* o,int f) { return (o->flags&f)!=0; }
static inline void lv_obj_set_size(lv_obj_t* o,int w,int h) { o->w=w; o->h=h; }
static inline void lv_obj_center(lv_obj_t* o) { (void)o; }
static inline void lv_obj_set_scrollbar_mode(lv_obj_t* o,int v) { (void)o; (void)v; }

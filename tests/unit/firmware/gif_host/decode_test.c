#include "gifdec.h"
#include <stdio.h>
#include <assert.h>
#include <string.h>
#include <stdlib.h>
size_t input_length;
static size_t live, peak, allocations;
static int fail_next;
size_t tracked_live(void) { return live; }
size_t tracked_peak(void) { return peak; }
void* tracked_malloc(size_t n) {
    if (fail_next) { fail_next=0; return NULL; }
    size_t* p=malloc(n+sizeof(size_t)); assert(p);
    *p=n; live+=n; if(live>peak) peak=live; allocations++;
    memset(p+1,0xcc,n); return p+1;
}
void tracked_free(void* p) {
    if(p) { size_t* s=(size_t*)p-1; assert(live>=*s); live-=*s; allocations--; free(s); }
}
void* tracked_realloc(void* p,size_t n) {
    size_t old=p?*((size_t*)p-1):0;
    void* q=tracked_malloc(n); if(!q) return NULL;
    if(p) { memcpy(q,p,old<n?old:n); tracked_free(p); }
    return q;
}
int main(int argc,char**argv) {
    assert(argc>1); printf("[\n");
    for(int i=1;i<argc;i++) {
        FILE*f=fopen(argv[i],"rb"); assert(f); fseek(f,0,SEEK_END);
        input_length=ftell(f); rewind(f); unsigned char*input=malloc(input_length);
        assert(fread(input,1,input_length,f)==input_length); fclose(f);
        peak=0; fail_next=1; assert(gd_open_gif_data(input)==NULL); assert(live==0);
        gd_GIF*g=gd_open_gif_data(input); assert(g && g->width==240 && g->height==240);
        int count=0,result; uint32_t rolling=2166136261u;
        while((result=gd_get_frame(g))==1) {
            g->loop_count=1; assert(g->gce.delay==8);
            assert(g->fx+g->fw<=g->width && g->fy+g->fh<=g->height);
            gd_render_frame(g,g->canvas);
            for(size_t j=0;j<240*240*4;j++) rolling=(rolling^g->canvas[j])*16777619u;
            count++; assert(count<=40);
        }
        assert(result==0 && (count==30 || count==33 || count==35));
        gd_rewind(g); assert(gd_get_frame(g)==1); gd_render_frame(g,g->canvas);
        gd_close_gif(g); assert(live==0 && allocations==0);
        // 反复创建/切换，每次都先销毁，验证释放及首帧解码。
        for(int k=0;k<100;k++) {
            g=gd_open_gif_data(input); assert(g); assert(gd_get_frame(g)==1);
            gd_render_frame(g,g->canvas); gd_close_gif(g); assert(live==0 && allocations==0);
        }
        printf("{\"file\":\"%s\",\"frames\":%d,\"peak_decoder_bytes_host\":%zu,\"frame_fnv32\":%u,\"switches\":100}%s\n",
            strrchr(argv[i],'\\')?strrchr(argv[i],'\\')+1:argv[i], count,peak,rolling,i==argc-1?"":",");
        free(input);
    }
    printf("]\n"); return 0;
}

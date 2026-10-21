# AH：0016 圆屏字幕与 TTS 打断消费者候选

2026-10-21。源码冻结提交 `e63441a420e00fcbe3a8eafeb12c31eaa3acb11a`。之后仅补迟到Speaking测试和交付记录，8个外部源码/版本文件及镜像保持该冻结点。这是一份离线候选交付，待ROOT/AI联合审查；没有操作COM3、烧录、切换日用服务或取得owner新一轮体验验收。源码、补丁、native验证和最终构建已绑定；不把阶段性final1镜像当成最终镜像。

## 范围与来源

基线是已有0015导出源码 `D:/Dev/esp-projects/smart-ring/otto0015`，不是Git工作树。其板级文件、application和版本入口先与0015既有实验指纹核对；随后保留完整10,765文件复制前摘要。官方vendor固定提交 `c4bdbab349e44cfc74fa6912f923193e9d389c7e`，ESP-IDF 5.5.4固定提交 `735507283d5b2f9fb363a1901172dbd9e847945d`，本次均实际只读核验。

独占ASCII源码为 `D:/Dev/esp-projects/smart-ring/ah-otto0016-subtitle`，物理复制已装组件，不建联接、不下载、不复制旧build。完整核对及最终构建后的再核对证明：原0015未动，候选仅下面8个文件不同，另10,757文件一致；没有新增资源、分区或配置变化。

| 范围 | 文件 |
| --- | --- |
| 字幕与版本 | `main/boards/viewe-smartring-plus/viewe-smartring-plus.cc`、根 `CMakeLists.txt` |
| 控制与UI回调 | `main/application.cc/.h` |
| 音频门、活动任务和输出屏障 | `main/audio/audio_service.cc/.h` |
| hello和本地连接来源 | `main/protocols/websocket_protocol.cc`、`main/protocols/protocol.h` |

未修改 `websocket_protocol.h`、`protocol.cc`、其他板型、素材、SDK、原始vendor、其他应用槽或设备存储。内部 `longmemory` 名称沿用。

每个文件的原始字节数/前后SHA、两补丁SHA、完整源集审计摘要、native日志摘要及最终BIN/ELF/map/分区表SHA见 [0016固定记录](../../../firmware/smartring_plus/experiments/0016-round-subtitle-interrupt.json)。证据根为本AH工作树的 ignored `data/test-tmp/ah-round-subtitles-20261021/`；完整源集摘要在 `frozen-source-v4/source-audit.json`。

## 字幕原因和修复

0015先设272×58底栏、252×48标签及底部偏移-38；实际通用多行 `LcdDisplay::SetChatMessage` 每次又把底栏对齐复位到底部0。真实LVGL/原字体回放得到标签矩形 `(54,307)-(305,354)`，已越出理想圆边。原字体名为20但行高25，48px也放不下两行；DOT模式会省略超出内容。仅改服务器切段不能修复几何和通用消费者复位。

0016在同一个递归显示锁内更新正文并恢复板级布局：224×58透明底栏、底部偏移-52，220×54标签、2px行距。真实坐标为标签 `(70,252)-(289,305)`、容器 `(68,250)-(291,307)`，两矩形四角均通过半径179.5、中心179.5且保留8px余量的圆内断言。保留整屏黑底和现有配置/壁纸。

正文仅按原字体的LVGL实际宽度增加显示换行，不删除标点/原有换行、不切UTF-8字节；常用组合音标、变体、肤色、ZWJ（零宽连接符）及区域旗帜对作为组处理。它不是完整Unicode字素分段或新增字体覆盖承诺，复杂文字/未覆盖字形仍需另验。

标签使用纵向往返滚动，24px/s，首屏延迟900ms，末端/重复停留1200ms；新正文从头开始，隐藏/空正文沿原语义。没有改TTS音频切段或伪造字级时间戳。下一条sentence_start仍按原时机替换字幕，所以离线证据不保证真实语音节奏下每条字幕都有足够时间完成一轮显示。

`prepare_subtitle_native.py` 提取候选实际换行、布局和override方法，用原 managed LVGL、`font_puhui_20_4.c` 在MSVC上编译并软件渲染360×360 RGB565；通用显示基类和锁为单线程替身，实际esp_lvgl_port的递归锁另经源码核对。最终日志 `native-caption-final-run.log`：短句、标点长句、五句正文、原换行和常见组合字符均保留正文，每行宽≤220，全部行完整进入54px可视区。

五句正文排12行，首次移动900ms、最后一行于10220ms完整进入；其他三行用例首次移动900–920ms。native同时运行独立40ms对象刷新，滚动未复位，另有新正文复位/隐藏断言。源码只读核查：实际 `FaceTimerCallback → ApplyFace`、`ShowOtto` 的GIF帧回调不调用SetChatMessage/ApplySubtitleLayout；稳定视图的 `ApplyViewStyles` 早返回，只在视图改变时更新颜色/背景。该“源码路径+共享计时器”证据不是实际GIF解码、真机帧率或视觉验收。

可查看 `native-preview-v4/five_sentences-start.png`、`five_sentences-last-visible.png`、`0015-clipped.png`：均为此前同一字幕补丁SHA的LVGL/原字体软件渲染，没有Otto主体，不是设备照片。最终独立40ms刷新验证帧在 `native-preview-final/*.ppm`。

## 打断协议和本地身份

依据AD合同修订3 `2b8242e5` 实施；只读参考服务端交付 `ff6ef6e6615017b14f1c91192a341e1b08410560`，未在AH接入/审查完整服务端。ROOT后续明确：普通EOS（自然结束）不清尾音；之后用户明确打断，可以同epoch interrupt撤销仍未排空的尾队列。该澄清的最终服务端合同/实现由AI整合。

本板WebSocket客户端声明 `features.tts_interrupt_v1:true`，收到首次有效server hello的严格布尔true才启用。缺确认、false、字符串true保持legacy；其他板型不声明，MQTT不协商。重复hello不能换模式或重置轮次；v1的非法/缺失epoch忽略，不降级。线上整数范围1..2147483647，只有更大start能开新轮，同epoch start不能复活撤权输出。

所有设备工作绑定本地 `(channel_generation, output_epoch, audio_generation)`。64位RAM代次只增长，不写JSON/NVS，连接关闭也消耗失效代次，跨Protocol实例不重置；溢出不回绕。旧socket闭包捕获固定通道，dispatch与关闭共用屏障。断开/换通道先失效，旧hello、音频、close及延迟UI不得碰新连接。

新start在接收路径同步撤销旧轮、完成解码器/输出屏障，再开新音频门，随后才安排UI；接收首帧不依赖Speaking已显示。晚到的合法Speaking及间接EnableVoiceProcessing不再清新首帧。控制、UI核对与副作用共用应用屏障；解码、重新入PCM队列及开始OutputData在各自共同屏障重核身份。

正常stop关闭继续接收的门但保持已有任务有效，排空同时覆盖待解码/待播队列、出队前同锁增加的active_decode/active_output，以及OutputData返回。旧任务只能减自己计数。interrupt、本地AbortSpeaking、关闭或新start撤销旧轮，清本轮旧队列并取消旧EOS；本地abort先撤门再发原上行abort。EOS已到但仍在解码/输出时也可明确interrupt。EOS回调即使已排队，执行时仍须身份有效。

另修复legacy→v1重连边界：未带v1 output identity的WebSocket包仍保留不可变channel_generation，传到PCM；换通道清旧网络队列，已出队decode/PCM重新核对原通道，不能标为新连接。通道0本地提示音保留。该隔离补强不要求旧服务器增加epoch。

二进制v1/v2/v3格式不变；因此服务端所有TTS控制及二进制共享最终发送门是必要前提，AH测试不能替代AI对服务端覆盖/装配的联合审查。没有新增“播放已停”回执。已经进入OutputData的调用允许返回，interrupt等待此屏障；不承诺硬件DMA或扬声器零毫秒静音。

## 消费者实际CPU验证

`prepare_tts_interrupt_native.py` 从固定源提取实际身份、通道helper、队列入队、解码分支、输出任务、音频门、应用协商/控制/调度/abort/状态方法，以SDK原cJSON编译。只在生成的测试翻译单元加入handoff、decode重新入队和PCM出队三个暂停hook。硬件codec、Opus、FreeRTOS为替身；legacy JSON分发用最小模型，完整实际legacy方法由目标构建编译。不是板上代码执行或真实音质测试。

最终 `interrupt-native-v4/source-binding.json` 绑定源SHA及提取段SHA；MSVC Debug两个目标退出0：

- EOS在decode出队/计数交接及解码阻塞时不假空；最后PCM完整输出后才完成。EOS在OutputData阻塞时等其返回。解码失败/异常、输出异常归还自己活动计数。
- 撤权后已出队decode不得重新入队，已出队PCM不得开始旧输出；解码入口屏障、满队列等待者均拒绝旧身份。旧任务finally不伤新连接epoch1的队列/计数。
- legacy已出队decode/PCM暂停，关闭后建立v1新连接epoch1，再释放旧工作，新首帧保留且旧音不输出。
- 暂停UI时start后立即收首帧；随后Speaking/EnableVoiceProcessing不二次清帧。重复start、旧stop/interrupt、旧Speaking/Listening/EOS及旧连接hello/close无效；本地abort先撤旧门。
- 普通EOS保持尾帧；EOS后interrupt取消未完成排空。真实排空回调已排队→同epoch interrupt→新start，旧回调仍不改变新轮。已进入OutputData的调用被允许返回，屏障完成后不开始旧输出。
- 严格epoch、缺失epoch不降级、重复hello、未确认/false/字符串true回退、本地代次耗尽关闭；另编译未声明客户端目标，server单方面true不启用v1。通道dispatch/关闭屏障及跨实例代次不复用通过。

原始结果 `interrupt-native-run-v4.log`、`interrupt-native-legacy-v4.log`。这组离线验证没有运行官方服务器、MQTT实连、真实Opus解码、真实设备或日用服务；未证明最终组合装配和owner听感。

## 最终构建与审计补丁

最终目录 `D:/Dev/esp-projects/smart-ring/build-ah-otto0016-subtitle-20261021-final2`。首次新目录尝试在CMake前被离线guard误拦内部socketpair；失败日志保留。修复仅子Python进程内socketpair调用的例外后，完整2164步构建退出0，ccache关闭，未复用0015/初步build。final1与初步字幕镜像来源较早，均不是本次交付镜像；没有第二次独立重建最终源码。

最终应用：

`D:/Dev/esp-projects/smart-ring/build-ah-otto0016-subtitle-20261021-final2/xiaozhi.bin`

- 4,011,456 bytes（`0x3d35c0`）；SHA256 `caca8cbf7b8b1df715c9523c1f32321d8b32b309acb63adf2e710d7f9901193c`。
- 最小app分区4,128,768（`0x3f0000`），剩117,312（`0x1ca40`），编译器近满3%提示保留；不占别的分区来扩容。
- esptool4.12本地image_info扩展检查：ESP32-S3、版本 `2.2.3-otto0016`、ESP-IDF v5.5.4、校验/validation hash有效；它只读BIN，不打开串口。
- 分区表SHA与0015既有记录一致。构建产物有bootloader/assets等，但不属于更新目标；生成的全片flash示例绝不能作为本任务执行命令或授权。

按序应用 [字幕补丁](../../../firmware/smartring_plus/patches/0016-round-subtitle-safe-area.patch) 和 [消费者补丁](../../../firmware/smartring_plus/patches/0016-tts-interrupt-v1.patch)：SHA分别 `33b43cb4d66b9c28a7c9ac5d5b93c551ef58542f774718e03ada8a900665adc4`、`a5f4a9c0d89d2c280c3976ebba9b99585c681f21aa0e7db6f95eebcd6ee6ebaf`。`audit_0016_source.py` 在新8文件fixture实际apply/check及逆序reverse/check，逐字节吻合候选并还原0015。Windows须用命令级 `git -c core.autocrlf=false -c core.eol=lf apply ...`，不能只依赖全局autocrlf。早期审计工具缺EOF标记/原生CRLF转换的失败fixture保留，修复的是审计工具，不是反复修改固件来凑通过。

ROOT整合需为两份0016补丁补 `text eol=lf` 属性（同既有0013–0015），并登记本独立记录到共享manifest；AH未越界改共享文件。两份补丁的Git blob/current raw SHA已核对。实际对本记录及d286记录运行 `--only --strict` 退出1，报unknown-selection，实际检查正文0篇，另提示本树三份AH新文档未登记，不能冒称正文检查通过。本记录人工核对代码/证据，4个本地Markdown链接均存在，原始检查结果保留为 `docs-strict.json`、`manual-doc-links.json`。

本次CI可见性接力另见 [d286验证](AH-ci-visibility-20261021.md)：其代码 `e5fcca1e`、记录 `38a04d4b` 可独立接力，不属于固件接口或日用切换。后续由ROOT/AI按固定源联合审查，再由ROOT安排下一阶段；本交付不授权刷写，也不替代owner字幕、声音、插话和多轮实际体验。

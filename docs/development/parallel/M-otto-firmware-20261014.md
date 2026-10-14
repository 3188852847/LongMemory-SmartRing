# M：0014 Otto 固件适配与离线验证

日期：2026-10-14，Asia/Shanghai。独立分支 `codex/otto-firmware-0014-20261014`，基线 `a041b5f`。完成离线适配、真实资源保留重包、审查修正和干净编译；设备写入与实机验收由 K/所有者另登记。

## 范围与当前路线

本会话只适配、重包和编译；没有串口、复位或烧录操作。原 `src`、`motion0013`、已有 build、SDK、环境锁和私有配置不修改。独立 ASCII 源码为 `D:\Dev\esp-projects\smart-ring\otto0014`，最终应用来自 `build-otto0014-clean5`，同源码独立 `build-otto0014-clean6` 重建通过，均空目录、禁用 ccache（编译缓存）、外部 Python 网络连接/DNS（域名解析）被阻断。

21 个固定 GIF 共 1,609,459 字节，不嵌入应用。沿真实 `Assets::LvglStrategy` 格式追加到 assets：12 字节头、44 字节表项、`ZZ` 数据前缀；保留原表项名称、尺寸、偏移、资源字节和整个原 payload 区域，原 index.json 不改。新增表区会使实际资源物理地址移动，应用均按名称重取。无新依赖、分区或文件系统；assets 不是 SPIFFS。

K 交付的精确原 assets 为 2,097,152 字节，SHA-256 `d4bd1827b792b257d7225d7139f2698d37eb6988a1630f5e745f2d9214735d3a`；M 只读该映像和允许的表级元数据，没有读取全 Flash、NVS 或原始日志。M 独立确认其有效前缀 352,105 字节与本次干净编译生成的默认资源逐字节一致，SHA-256 `c31a144a0df77bfd8f70545d3af12e3b23f1501cc3b4865ebd91e0fcac965478`。这次有真实设备映像证据，没有用默认资源代替它。

原 23 个资源（srmodels.bin、index.json、21 PNG）逻辑字段、逐资源字节和整个原 payload 区域保留。字体继续使用原 sdkconfig 所选编入应用的字体，不新增字体资源。新 assets 为 44 条目，有效长度 1,962,530 字节；21 GIF 增加 1,609,459 字节，表项与 ZZ 前缀增加 966 字节。

原有效长度外有 1,731,795 个非 `0xff` 未索引字节，来源尚未判定。`Assets::LvglStrategy` 及其 index/name 消费、唤醒模型载入、板级壁纸和通用 mmap 组件均经表/名称或独立壁纸槽读取；源码未发现当前板型固定偏移消费该尾的路径。K 后续独立核对 983 个已编译源、资源索引和语音容器，也未发现消费者；这支持必要新增区重写，但不证明这些字节最初来源。详细证据在 [读取路径核查](../../../scripts/development/otto_firmware/tail-review.json)。

必要替换的未索引范围为 `[352105,1962530)`，共 1,610,425 字节，其中 1,598,167 字节原为非 `0xff`；不称为空白。新 used 之后的 134,622 字节原尾逐字节保持，末扇区中 3,550 字节随包写回，`0x9e0000` 之后不擦写。原整分区保存在 K 已验证备份，支持精确回退；不声称整个 assets 原样未变。

## 显示与真实事件

Otto 240×240 原图居中，保持原状态栏与字幕。默认 Otto 优先于原壁纸；原壁纸分区和 NVS 均保留，新增 UserOnly（仅用户可调用）工具 `self.screen.set_round_face_view`，参数 `view=otto|wallpaper`，只切当前运行视图，重启恢复 Otto。原壁纸查询、暂存、激活和回退工具继续存在；本任务不调用会写配置或分区的壁纸工具。现有皮肤设置仍管理回退几何脸及文字颜色。

Idle/Connecting/Listening 用 neutral；真实 stt text 在 Listening 才显示 thinking；Speaking 取本輪缓存的 llm.emotion，未知值 neutral。系统提示与服务端 emotion 分开，经兼容虚方法仲裁，防止 `thinking` 等晚到值改变 Listening。进入新 Listening/Idle/Connecting 清缓存；tts.stop 保持原 ManualStop→Idle、其他→Listening 分支。插话仍走原 Abort 与立即采集，650 ms surprised 只控制显示，无新音频/连接超时。正常 OnAudioChannelClosed 仍 Idle neutral；仅真实系统故障提示使用 confused，cloud_slash/wifi_off 使用 sad。

协议没有 turnID（回合标识），无法识别已经进入下一轮 Thinking/Speaking 后到达的上一轮 emotion；这是本地仲裁的已知边界。展示状态可以由下一次真实状态事件恢复，不锁定连接/音频状态机。

仅一个活动 GIF 控制器，换图前解除 LVGL 对画布引用并释放旧控制器，首帧立即解码。缺素材或解码失败回 neutral→保留壁纸→原几何脸；同状态不重复解码，失败资源单独以 1 秒限重试。原 40 ms 定时器仲裁提示到期、解码错误和回退几何脸。GIF 解码回调遇到中途错误只设置 HasDecodeError 并暂停，由显示仲裁回调释放；合法暂停/正常结束不当作错误。壁纸请求成功以实际 wallpaper 来源和可见标记判断；失败返回 false 并恢复原回退。

## 已取得的离线证据

固件实际 `gifdec.c` 在 MSVC 19.51 的桌面桩环境解码 21 图 / 692 帧，加入输入读/seek边界断言、240×240矩形检查和 80 ms 帧延时核对。每图 100 次创建/首帧解码/释放通过，零残留分配，分配失败路径返回空控制器。桌面解码器申请峰值 326,560 字节（含 realloc 同时保留旧表时的峰值），不包含 LVGL、音频、RTOS（实时操作系统）及目标机分配器开销，不代表真机可用堆或帧率。

纯 C++ 状态仲裁覆盖迟到 emotion、当前轮缓存、未知值、错误优先、恢复、650 ms 临界点、时钟回绕、主动 TTS 与 ManualStop 停止分支，通过。未连接日用服务或个人库。

主会话/N 的审查定位系统 thinking 被误缓存、中途解码未回退、壁纸切回隐藏及失败误报成功。全部修正后，测试机械抽取最终板级 ClearGif/ShowOtto/TryLoadWallpaper/SetStatus/SetEmotion/SetServerEmotion/SetFaceView 和仲裁入口，配合真实 LvglRawImage 与 LvglGif 控制器、gifdec.c；LVGL 对象/计时及分区用桩，几何绘制尾部不测试。真实调用顺序 Listening→状态思考→系统 thinking→Speaking 无 LLM 时 neutral、有 happy 时 happy；服务端 thinking 仍可缓存。定向构造首帧和中途解码错误，证明 neutral/壁纸/几何回退、非自身回调安全删除、999/1000 ms 重试、壁纸错误后 neutral→壁纸恢复；合法暂停/结束不误判。Otto→壁纸→Otto 实际对象隐藏 flag 和 240/360 尺寸通过；缺壁纸返回 false 且 Otto 可见。

资源合成测试 6 项通过：保留原 payload/index、固定上游指纹、未审核尾拒绝、精确审核哈希、末扇区及未写尾保留、checksum/边界/ZZ/重名拒绝。一度因测试变量切到带私有尾合成映像而先触发尾门槛，修正为原本欲测试的 indexed-only（只有有效索引包）夹具；没有为测试放宽实现。

第一次配置的网络护栏以 RuntimeError 中断组件版本查询，失败目录 `build-otto0014` 保留。改为标准 socket OSError/gaierror 后，已装 Component Manager 走其原生离线 fallback（回退），未改 SDK 或依赖。`offline`、`clean1` 至 `clean4` 为审查前阶段产物，保留但不是本次烧录输入；最终 `clean5/clean6` 均 3,990,640 字节、应用余 138,128 字节，分区表与默认资源 SHA-256 一致。应用含构建时间与 ELF（可执行链接格式）摘要，独立重建不要求应用逐字节相同。

本次 SDK/组件锁和 sdkconfig 与 0013 原文件 SHA-256 相同；目标 GCC 明确 `__CHAR_UNSIGNED__=1`，符合 assets sum16 字节校验。官方 esptool 4.12.0 的纯本地 image_info 核验最终镜像 checksum/validation hash 有效。保留供应商 `_IO/_IOR/_IOW` 宏重定义及应用余量 3% 提示；桌面桩编译的 64 位 size_t→32 位转换警告属宿主差异，所测输入均在 2 MB 内。没有改供应商代码以消除无关警告。

最终 [补丁](../../../firmware/smartring_plus/patches/0014-otto-gif-face.patch)覆盖 7 个源文件，采用零上下文格式，应用需 `--unidiff-zero` 并核对来源摘要；避免将厂商上下文空白当本项目新增尾空格。正向应用到独立最小原源码夹具、逐结果摘要核对及反向检查通过；适配脚本生成结果与最终独立工程逐文件字节相同。完整摘要、逐原资源保留记录及桌面桥接源摘要见 [实验记录](../../../firmware/smartring_plus/experiments/0014-otto-gif-face.json)。原始/派生二进制与日志不提交。

## 固定交接与后续边界

| 产物 | 固定路径 | 字节数 | SHA-256 |
|---|---|---:|---|
| 应用 | `D:\Dev\esp-projects\smart-ring\build-otto0014-clean5\xiaozhi.bin` | 3,990,640 | `b87f358d009bad469e82119067a5f8f3453f589696b9d1d22cc4502ce0dc684b` |
| assets 最小写包 | `D:\Dev\esp-projects\smart-ring\otto0014-assets\otto-assets-prefix.bin` | 1,966,080 | `a90519236d915d985e12940d753504011506e3a8135fc8d8a5dc62c55173053f` |

assets 固定地址 `0x800000`，写/擦除终点 `0x9e0000`；应用地址由 K 再核实际活动槽。新 assets 全分区预期 SHA-256 `5574d85a67b534caac78748573d3dcf8438c7fd3c5d0f14d3404d12fcf364024`。精确范围及回退见 [指南](../../guides/Otto动态表情固件-20261014.md)。不要使用旧产物或构建默认 flash_args。

最终板级源码 SHA-256 `636942d8ae6cb4f7a336f14be5199c737f8c234c6a04525ba27dfb91851bb274`，与主会话转交的 N 四项复验/30 次视图往返报告 `f6b7cfe` 指纹一致。N 的独立通过与 M 的桌面/编译证据均不代替设备验收。

三份新增文档及清单 strict（严格）检查通过，零 warning/error，两条 note 为检查器按 `experiments` 路径组件跳过公开 JSON 链接；该实验记录已人工核对，源码关联采用仅匹配本次补丁/JSON 的 0014 glob。`git diff --check` 通过；公开文件无原映像、原/派生固件、私人图片、日志或凭据。根 README/AGENTS/ROADMAP/CHANGELOG 和主任务书未改。

本会话仅本地提交分支，不合 main、不推送、不给其他会话发消息。主会话审查后交 K 唯一串口会话，登记合入提交与后续实机结果。真机视觉、帧率、语音并发、插话、设备读回均不在 M 的完成证据中。

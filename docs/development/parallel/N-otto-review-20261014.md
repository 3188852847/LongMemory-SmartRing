# N：0014 Otto 烧录前独立审查

日期：2026-10-14，Asia/Shanghai。审查树 `local/worktrees/otto-0014-review-20261014`，分支 `codex/otto-0014-review-20261014`，基线 `8fd38c02b7625db595c1c1194c87f9c99425cd92`。

## 当前结论与交接

**尚未满足烧录前技术验收：M 正在修改且未提交最终版本；原壁纸运行时切换存在实际显示缺口。** 这不是要求所有者再次批准；主会话可安排 M 修复后提供固定提交与最终产物，N 继续窄范围复核。

N 没有串口、复位、烧录、联网下载或日用服务操作，没有读取设备 Flash/NVS、原始串口日志或私有备份正文。只读取 M 任务代码、公开实验摘要、独立 ASCII 源码和公开生成的默认 assets。

## 可行动发现

1. **原壁纸成功加载后仍可能隐藏。** 当前 `SmartRingFaceDisplay::SetFaceView("wallpaper")` 调用 `ClearGif()` 后给复用的 `wallpaper_image_` 加 `LV_OBJ_FLAG_HIDDEN`；`TryLoadWallpaper()` 成功分支复用对象、设置图像、标记 ready 并 Start，但没有取消隐藏。随后 `ApplyFace()` 因 ready 隐藏几何脸并返回，工具仍返回 true。正常 Otto→wallpaper 这条实际入口即可触发，无需素材损坏。修复应在壁纸成功安装后取消图片隐藏，并定向验证 Otto→wallpaper→Otto。
2. **同一工具的失败结果需按活动来源判断。** 新修订在 wallpaper 视图加载失败时回 neutral，这会令 `wallpaper_ready_` 成为 true；`SetFaceView` 只看 ready 判断成功，可能把 neutral 当作 wallpaper 成功。应按 `active_gif_ == "wallpaper"` 或等价实际来源决定工具返回值与 wallpaper 重试；不把回退成功误作壁纸加载成功。

上述位置以实际 ASCII 文件 `D:/Dev/esp-projects/smart-ring/otto0014/main/boards/viewe-smartring-plus/viewe-smartring-plus.cc` 为准。动态修改期间行号会改变，定位方法名与精确调用链。

## 两个原阻断点的修订复核

- 当前修订已令系统 `SetEmotion` 调用 `SystemEmotion`，仅系统故障改变 Error/Disconnected；thinking、microphone 不写服务端缓存。`SetServerEmotion` 单独调用 `Emotion`。实际 STT 顺序是 SetStatus(thinking)→SetEmotion(thinking)，之后 tts.start→SetStatus(Speaking)；此实现让无 llm emotion 的 Speaking 使用 neutral，修复方向完整。
- `LvglGif` 已增加 `HasDecodeError`，后续 `gd_get_frame < 0` 标记错误并暂停。另一个 40 ms 显示仲裁回调记录失败、解除图片引用、释放控制器，再走 neutral→壁纸→几何脸回退；不在 GIF 自己的回调释放自身。正常 `gd_get_frame == 0`、Pause/Stop 与 loop wait 不标记解码错误，避免把合法暂停当故障。首帧失败先 Cleanup；每资源 RetryGate 防止失败资源因快速状态切换反复解码。正式通过仍需绑定最终源码、测试与构建。
- 独立宿主桩从实际板级源码直接抽取 `SetStatus` / `SetEmotion` / `SetServerEmotion`，仅去除 `override`，使用实际 `otto_state.h`；MSVC 19.51、C++17 编译运行通过。验证上述 STT→系统thinking→Speaking、Thinking期服务端happy→Speaking、系统提示不覆盖happy、Listening迟到emotion、650ms到期、故障与重连/Idle恢复、主动TTS和未知值。桩未模拟LVGL画面和真实采集，因此不证明壁纸可见或真机语音正常。脚本：[otto_review_bridge.py](../../../tests/unit/firmware/otto_review_bridge.py)，局部产物仅在自己树 `data/test-tmp/otto-review-bridge-20261014-01/`。

## 真实事件与保留边界

- 实际 `OnAudioChannelClosed` 仍回 Idle，不引入故障脸。tts.stop 保留 ManualStop→Idle、其他→Listening。Listening/Idle/Connecting 清缓存；显示只在 Thinking/Speaking 接纳服务端 emotion。
- 插话仍调用原 Abort 与 SetListeningMode；650 ms 只控制 surprised 的显示期限，没有新增音频等待或采集定时器。已有 Listening 队列处理属于原音频逻辑。
- 协议无 turnID（回合标识）。上一轮 emotion 若在新一轮 Thinking/Speaking 才到达，本地无法可靠区分；这项真实协议边界须保留，不作完整跨回合隔离通过结论。
- 视图选择是运行时 bool，不调用 NVS 写入；原壁纸查询、暂存、激活和回退工具保留。原壁纸资源保留与实际显示成功分开验收，前者不掩盖上述工具显示问题。

## assets 独立核对

当前 `Assets::LvglStrategy` 依 stored_files 建表，资源物理位置为 `12 + 44 * stored_files + asset_offset`，GetAssetData 按名称并跳过 ZZ 前缀。追加21项后原物理资源地址增加924字节，原表内 offset 不变；调用者重新按名称取得资源，不保留旧绝对 Flash 地址。

静态检查当前板型的 assets、唤醒词与壁纸读取路径，未发现绕开有效表和 index.json 的固定偏移尾部消费者。未索引非 FF 字节来源仍未判定，不能称其已证实是历史残留。公开报告明确覆盖其中一部分，原完整分区回退证据由 K/主会话持有；N 不读取它。

独立合成检查使用公开 `build-otto0014-clean2/generated_assets.bin` 的23个资源和完整 payload，尾部全部改为合成 `0x12`，21个 GIF 内容也为合成字节，仅尺寸和大小模拟真实包，不把它们作解码/视觉证据。实际导入路径核对为 M 的 `scripts/development/otto_firmware/repack_assets.py`，解释器 `-B` 禁止在 M 树写 pycache。

| 检查 | 实际结果 |
|---|---|
| 原23项名称、尺寸、offset、宽高和资源字节 | 全相同 |
| 原整个 payload（包含间隙） | 前缀逐字节相同 |
| 新44项表及按名称重定位 | 通过，原物理地址增924字节 |
| 有效包/最小扇区写入 | 1,962,530 / 1,966,080 字节 |
| 地址范围 | `[0x800000, 0x9e0000)`，终点不包含 |
| 末扇区原尾 | 保留3,550字节 |
| 新 used 后整个原尾 | 保留134,622字节 |
| 非FF尾未审阅/原指纹错误 | 均拒绝 |

主机交叉编译器预处理确认 `__CHAR_UNSIGNED__=1`，与厂商 `char` 字节 checksum 以及 Python unsigned-byte sum16 一致。脚本不改分区、OTA（无线升级）数据或引导器；实际写入限制与烧录后保护区域读回由 K 另验。

可复核脚本：[otto_review_checks.py](../../../tests/unit/firmware/otto_review_checks.py)。本次局部合成结果在自己树 `data/test-tmp/otto-review-22152-04c5750d1b2d4a8181ed880414efda06/result.json`；不提交临时产物。

## 本次动态源码指纹与最终所需字段

本次观察已包含 M 正在修订的错误标记，不能用旧构建 `7a5258d7...` 作为其编译验收。归一化 LF 文本 SHA-256：

| 文件（相对 ASCII 源码） | 本次指纹 |
|---|---|
| main/application.cc | `d7fd88fa50803a98611388bbafed829bc074b5dd43851443bea8129d5aecf366` |
| main/display/display.h | `6fd42590a7baf8cd7043a2e18fb979ebdc87f0934c0edf506649944374a389d6` |
| main/display/lvgl_display/gif/lvgl_gif.cc | `0097eacf37050f55f8fa0376e67a10d077df7f517e8625c70c4965a71550e978` |
| main/display/lvgl_display/gif/lvgl_gif.h | `f18327bdc0fec90dd36339c952e2c27319b054453b9d2a839e05db3542b6cc4e` |
| main/boards/viewe-smartring-plus/viewe-smartring-plus.cc | `020a32d9b284de8044c347c189c79bd6a11bfde254bbda02cf47c741887e88c9` |
| main/boards/viewe-smartring-plus/otto_state.h | `b3edb212369a5abeadaff70bf8743567be5a36eb440cdff0776ed207b7422c4d` |

请主会话交付 M 最终提交号、审计补丁及源码指纹、最终干净构建目录与 app 大小/SHA-256、独立重建和镜像校验结论、精确 assets 写包 SHA-256 与完整分区写后预期 SHA-256、当前设备备份/活动槽已由 K 核对的摘要。N 随后只复核最终差异及上述待修项，不重做全仓测试，不替代 K 的设备核对或所有者真机体验。

# L：Otto 真实动态表情预览与状态方案

更新：2026-10-14。L 独立会话 `01a13abb-1934-7201-80e2-cefc61718811`，工作树 `local/worktrees/otto-preview-20261014`，分支 `codex/otto-preview-20261014`，基线 `06dcb5e5efff9c68d45b3c169ec45574b9a8c1b1`。首次核对无未知修改。所有编辑、终端、测试和本地服务均显式限定本工作树；未在主检出编辑/构建/启动。

## 范围与完成标准

所有者选定 txp666 的 Otto GIF 资源包。L 负责固定来源/下载命令、21 图真实圆屏预览、状态映射与仲裁、容量和适配建议、公开证据及本分支提交。素材下载由所有者执行。本轮后续所有者已要求继续真实预览并推进烧录，主会话明确仍由其他专属会话承担固件接入/编译与串口；L 没有取得或使用串口操作范围，不直接实施烧录。

完成标准：可追溯固定提交/许可；无覆盖的下载入口；真实 21 GIF 网格/单表情循环；360 画布的 240 居中和 1.5 倍缩放比较；实际事件与提议分列；快速切换、打断、晚到情绪、超时与故障回退可演练；默认尊重减少动态；保存实际验证、容量依据和未验证限制。电脑预览完成不等于固件/真机验收。

## 交付内容

| 文件 | 作用 |
|---|---|
| [使用指南](../../guides/Otto动态表情预览-20261014.md) | 所有者下载/启动命令、状态来源表、仲裁规则、容量及后续适配提议的权威入口 |
| [Download-Otto.ps1](../../../scripts/development/otto_preview/Download-Otto.ps1) | 固定 codeload 提交、Git blob 摘要核对、唯一 staging、拒绝覆盖、错误即停、会话代理恢复；UTF-8 BOM 兼容 PS5 |
| [serve.py](../../../scripts/development/otto_preview/serve.py) | 标准库只读回环服务，随机端口、固定白名单、路径逃逸/错误指纹拒绝、无写接口/目录浏览/日用端口 |
| [预览入口](../../../firmware/smartring_plus/previews/otto/index.html) | 21 图、圆屏尺寸比较、状态演练、暂停/播放、显式故障/减少动态演练 |
| [state.js](../../../firmware/smartring_plus/previews/otto/state.js) / [lifecycle.js](../../../firmware/smartring_plus/previews/otto/lifecycle.js) | 可独立验证的状态仲裁与浏览器生命周期绑定 |
| [固定上游元数据](../../../firmware/smartring_plus/previews/otto/upstream.json) | 组件 `1.3.0`、commit `970cf66906d7c30059faa2704e7002f06b8c3619`、23 文件大小/Git blob SHA-1 |
| [实际素材核验](../../../firmware/smartring_plus/previews/otto/asset-verification.json) | 21 图尺寸、帧数、延时、各文件本机计算的 SHA-256；不含原 GIF 字节 |
| [固件只读依据](../../../firmware/smartring_plus/previews/otto/firmware-evidence.json) | 所读 0013 源码/构建文件摘要与分区、资源预算；不是本次芯片读取 |
| [状态测试](../../../tests/unit/development/otto_state.test.cjs) / [服务测试](../../../tests/unit/development/test_otto_preview.py) | 合成状态/生命周期及只读服务边界；不写个人库，不连日用端口 |
| [第三方许可说明](../../../firmware/smartring_plus/previews/otto/THIRD-PARTY-NOTICES.txt) | 截图中上游图像的来源与完整 MIT 版权/许可文本 |

原始素材仍只读消费所有者新下载的 `local/runtime/otto-emoji/<固定commit>/`。未使用其他 local 私有资料；没有提交源码 ZIP、GIF、个人信息或设备原始备份。

## 实际检查

- 上游仓库、固定 commit、组件清单/API/CMake/许可通过只读网页与 GitHub API 核对。组件只提供 21 个名字、计数和版本，并非已嵌入/播放 GIF 的库。Git blob 比对与独立发行 SHA-256/签名不是同一件事：没有后者的发布认证。本机 SHA-256 仅作取得字节的后续追溯。
- PowerShell 下载脚本 ParseFile 无错误，PS5 子进程 `-ExecutionPolicy Bypass ... -ValidateOnly` 通过；已知 `hello` Git blob 摘要向量通过。L 没有执行下载；所有者反馈无报错，之后主/L 分别只读核验固定目录。
- 21/21 固定大小与 Git blob 摘要通过，总 1,609,459 B。结构检查全部 240×240，延时均 80 ms；neutral 35 帧，angry 30 帧，其余 19 图各 33 帧，共 692 帧。Windows 自带 System.Drawing/GDI+ 逐帧选择并创建解码位图检查 692 帧通过，无新依赖安装。
- 状态/生命周期 Node 原生测试 **9 项通过**；Python 标准库合成测试 **5 项通过**。后者核对导入来源在本工作树、固定素材预算、缺失/未知/损坏素材、GIF 截断、HTTP 白名单/遍历拒绝与 POST 拒绝。测试临时目录位于自己树 `data/test-tmp/otto-preview/`，仅清理各自唯一目录。
- 文档合成测试 **14 项通过**，显式将当前工作树 `src` 加入该子进程模块路径并验证源码来源；两个新增文档的 `--only ... --strict` 检查无错误/警告，仅 1 条既有实验清单的私有/外部边界 note。没有宣称全仓文档语义核对完成。
- 实际应用内浏览器逐一点击 21 图，主预览 `data-asset` 与所选名一致，21 图网格解码通过、零回退；网格静帧/播放与单表情检查可切换。原素材真实眼睛形态可见，没有绘制替代动画。
- 1366×768、1440×900 视口下两个比较画布实测均 360×360；原图居中区域 240×240、放大区 360×360。默认选原 240 居中，保留放大作对照。375×812 视口下客户区 360px（含滚动条差），文档宽同为 360px，无横向溢出，圆形保持 1:1；键盘 Enter 暂停通过。浏览器字号缩放未单独验收。
- 浏览器任务：聆听→STT 思考→缓存 happy→TTS 说话显示 happy；打断后聆听 neutral，晚到 happy 不覆盖；断线后说话事件不解除故障；连接超时进入错误；单图模式不因右侧状态改变所选素材。故障回退演练分别通过当前图缺失→neutral、当前图解码失败→neutral、全部不可用→静态文字；它们是显式模拟，没有损坏或改写真素材。
- 暂停后可见 canvas，活动 img 的 src 被卸载；主动播放重新载入原 GIF。减少动态演练走与实际偏好事件共用的暂停路径通过；页面未修改系统设置。隐藏/减少动态真实事件绑定由合成 EventTarget 测试通过，详见下方实际环境限制。

当次预览服务：`http://127.0.0.1:49578/`，独立随机选出的端口；地址仅在本服务存活期间有效。进程启动命令与重开方法在使用指南，Ctrl+C 停止；未使用日用 8767/8000/8003。

## 推荐交接方案

默认 240 原图居中。待机/连接/聆听 neutral 配既有状态文字，思考 thinking，说话显示当前轮 emotion，打断 surprised 短提示后 neutral 聆听，错误 confused，断线 sad。打断 650ms、连接 15s/思考 20s 看门狗、独立断线展示、故障锁定及明确恢复均为建议，未存在的协议事件不新造。`turn` 是预览本地轮次；实际 JSON 无回合 ID，不能宣称彻底解决跨轮乱序。

断线映射仅用于明确异常断线证据；`OnAudioChannelClosed` 也可能是正常结束音频会话，当前回 Idle 应保持 neutral，不能全部变为 sad 锁定。WebSocket 底层关闭走音频通道关闭回调；Protocol/MQTT 有 OnDisconnected 回调，但当前 Application 未挂接专用断线显示。当前 SetEmotion 的保留状态字串也可能改变展示交互，后续适配须明确事件来源。

适配建议及容量只维护在指南：当前应用余 142,384 B，21 GIF 1,609,459 B，不能全部嵌入；现有 2MiB assets 构建包有理论容量但使用自定义映射表，实际装机内容未读，不授权重包/写入。`IsGif360` 与壁纸解码尺寸限制、A/B 壁纸分区和 `round_wallpaper` NVS 需保留。后续显示模式/持久资源布局改变时另写 ADR（架构决策记录），不在 L 预览中改变契约。

## 公开视觉证据

[完整21图网格与页面](../../../firmware/smartring_plus/previews/otto/evidence/grid.jpg)、[原240与放大360比较](../../../firmware/smartring_plus/previews/otto/evidence/compare.jpg)。截图只含公开第三方素材与本地预览状态；MIT 说明随证据保留。截图是某一瞬间，循环解码与交互证据按上方实际操作记录判断。

## 未验证项与边界

- 当前应用内浏览器在切换到本次空白页、隐藏浏览器面板时仍返回 `document.visibilityState='visible'`，没有派发实际 hidden；系统减少动态偏好当时为 false。没有据此声称真实系统隐藏或操作系统偏好切换验收通过。共用暂停路径/合成事件通过，但真实浏览器事件派发尚需在支持该行为的宿主复核。临时空白页已关闭，临时视口测试结束后恢复。
- GDI+ 和浏览器可解码不等于当前 LVGL 解码器全部帧通过；未做固件编译、内存/帧率、连续播放时长、音频并发或真机动态验收。
- 没有打开 COM3、复位、monitor、烧录；没有修改主 src、motion0013、SDK、配置、壁纸、NVS、assets、分区表、OTA 数据或 eFuse。未读取设备备份正文。K 的历史读回与保护核验不证明本轮 Otto 接入/实机体验。
- 本分支只提交自己文件，不合并 main、不推送、不向其他会话发消息；主会话安排整合与后续专属实施。归档须满足交付验收与合入条件，不把本地提交等同主项目合入。

提交号以 Git 交付输出为准；主会话整合后在收口账本补“L → 本分支提交 → 本报告验收 → 主项目合入提交 → 会话 ID”。

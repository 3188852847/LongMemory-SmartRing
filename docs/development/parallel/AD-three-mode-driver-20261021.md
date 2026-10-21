# AD：当前声线三模式对照驱动准备

日期：2026-10-21。基线 `c74b88834683080d4dc4ee4b770f48707ff5b349`，
分支 `codex/ad-three-mode-driver-20261021`，沿用 AD 干净隔离树；旧诊断分支和提交保留。
范围只有本记录、[专属驱动](../../../scripts/development/cosyvoice/benchmark_ad_three_modes.py)
及[合成测试](../../../tests/unit/development/test_ad_three_mode_driver.py)。未改生产代码、协议、配置、锁文件或共享清单。
继续使用 project-doc-maintenance 技能做本任务窄范围记录；清单登记留主会话整合。

## 可审查行为与设计修正

默认/`--plan` 只输出计划，不查健康、不加载编码器、不联网，也不启动/停止服务。
真实运行只连接 `http://127.0.0.1:18774/v1/audio/stream`；其他端口、别名、参数 URL
均拒绝，子进程 socket/DNS 同样限于固定端口。HTTP 直接消费固定 v2 长度前缀 WAV，
不走预置音频，不做 busy 重试、不回退完整 WAV。

核对 [service.py](../../../scripts/development/cosyvoice/service.py) `_speech_post` 后确认：
请求支持 input/response_format/stream/cache/delivery_mode，可选草稿 voice_profile，
没有按请求设 seed 的实现。旧基准是在模型进程内设种子，不能照搬成 HTTP 字段。
因此修正 [前轮建议](AD-buffered-diagnosis-20261021.md) 的“2710/2711 种子配对”部分：
本驱动使用相同公开文本、正逆序、两次重复的未控制随机种子对照，输出明确标记
`seed_control=unavailable_in_existing_http_api`；不修改服务或声线，不宣称逐种子配对。

两条文字直接作为完整 TTS 请求，文本已就绪，不再次经自然分段，不混入模型首字或记忆等待：

- 下午的阳光落在窗边。
- 我们可以先整理桌面，再慢慢安排接下来的事情。

每条文本先 buffered → incremental → adaptive，第二次逆序，共 12 次完整测量。
adaptive 请求服务的 incremental，再用现有 AdaptivePCMBuffer；其余模式复用现有
ContinuousPCM/PlaybackTimeline、现装小智 OpusEncoderUtils 与解码器，24kHz 单声道、60ms 帧。
本驱动验证 TTS 传输和上述策略，不是整个生产连接/撤权/设备播放链路的集成验收。

另做 1 次 adaptive 首个有能量帧后取消及 1 次同一编码器复用。
取消瞬间须健康观测到 generation_in_flight=true 且 active_requests>0；短句已生成完则
停止并明确报告缺少真实取消证据，不换更长文本重试。连续至少 5ms、幅值绝对值≥200
作为 PCM16 能量代理，可跨解码帧累计连续样本，不把分散峰值凑数，也不证明首字或听感。

每次记录首 PCM/Opus/能量代理、收到的采样数与时长、解码帧/补齐量、估算供给间隙、
客户端/服务清理与取消后复用、粗阶段诊断差值。后者有重叠且无新增 CUDA 同步，不能相加当纯 GPU 时间。
档案摘要只在内存比较；不持久化声线配置、摘要、健康原文、PCM、Opus 或音频文件。
已完成行即时写脱敏 JSONL；失败保留失败前结果及当前 operation_begin，不剔除失败行后宣称完整。

## 预算、资源前置与失败边界

本次没有真实执行。AI 审查后，主会话须另行协调：

1. 日用服务及其他模型工作暂停，只保留一个当前声线模型实例；不得为了端口隔离重复加载。
   沿用现有 fp16/hidden-only、固定外部源码与模型，禁用强制 buffered。
2. 外部受控启动器从本候选服务源码加载，显式 `profile_root` 指向主项目，使用
   `127.0.0.1:18774`。当前 service CLI 没有 profile-root 参数；不能默认在隔离树启动 CLI
   就读到了当前声线，也不能添加虚构参数。服务启动、缓存隔离、离线模型加载和恢复由主会话协调，
   此驱动不承担这些操作，不导出 TensorRT、不加载 vLLM、不安装下载。
3. 从外部实例启动前开始计时：最多 2 次启动/选中声线热身，每次≤15秒；加 14 次驱动请求，
   总合成调用≤16，启动/热身/资源检查也纳入总墙钟 300秒。驱动不会再补热身。
   热身计数由主会话受控启动记录证明，健康接口没有历史调用总数；驱动会再核对实际热身耗时。
4. 准备新收据，匹配候选提交、工作树、服务 PID/创建标识/映像、固定 URL、已审查 WDDM 桌面背景。
   驱动核对监听进程、GPU 项目窗口分类、已选身份、热身/适配/服务源码摘要与空闲状态。
   这不是物理 GPU 独占证明；不能沿用旧窗口收据。

收据 schema_version=1，scope=`ad-three-mode-external-single-instance`；必填字段按驱动
`validate_receipt`：reviewed_by=`main_session`、window_id、candidate_commit、checkout、url、
started_at_utc/expires_at_utc（含时区）、max_seconds=300、external_warmup_calls（1～2）、
service_identity（pid/creation_token/executable_path）、shared_desktop_baseline、physical_gpu_exclusive=false；
production_stopped、other_gpu_model_workers_stopped、single_model_instance、service_source_matches_candidate、
source_and_model_verified、external_service_startup_warmups_within_15s_each 必须为 true。
收据/原始资源证据留忽略目录，不提交。本驱动不自动制造收据或替主会话批准资源窗口。

每次 operation（含前后健康与清理）上限15秒；父进程独立监管，重复 begin 不得重置上限。
超时、busy、模式不可用、声线漂移、非正常 EOS、静音、取消证据缺失或清理不归零均停止，不补跑。
预算用尽只终止自有 CPU 客户端，关闭其连接，**不终止外部模型服务**。
CPU 客户端先加入既有 Windows Job（进程所有权容器）再获管道许可；其自有查询工具后代也随 Job 清理，
不会把收据中的外部模型服务加入 Job。合成预算截止后不新增调用，进程树退出确认可另有最多4秒清理宽限。
取消是协作式，不能保证正在执行的 GPU kernel 在期限内停止；失败摘要标注服务清理未确认，
主会话须另查服务状态，不能立即恢复日用或启动第二实例。

完整诊断门槛为12次测量及取消/复用全部完成、身份不变、无回退/忙/重启、采样和尾帧可核对、
取消后服务 generation_in_flight=false 且 active_requests=0、客户端线程退出。
两次重复用于定位，不自动挑模式、不代替真机首字、连续播放或打断听感验收。

## 命令及本轮验证

以下命令工作目录均为本隔离树；主 Python 为已安装3.12，真实客户端由驱动选择现装小智3.10。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/benchmark_ad_three_modes.py --plan
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 -m pytest tests/unit/development/test_ad_three_mode_driver.py -q
```

仅在上述资源窗口准备、审查与新收据完成后使用（本轮未执行）：

```powershell
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 scripts/development/cosyvoice/benchmark_ad_three_modes.py --run --receipt '<新窗口收据绝对路径>' --production-root 'D:/03-项目/01-正式项目/智慧圆屏' --output 'experiments/results/ad-three-modes-<唯一窗口ID>'
```

输出目录必须为本树 experiments/results 下的新目录，已有目录拒绝覆盖；只写 summary.jsonl。
真实模型、当前声线性能、Windows GPU/监听收据核查链路、真实取消仍待正式窗口验证。
本轮仅做专属测试和计划检查，不重跑218/171回归，不改变日用模式。

当前专属测试44项通过（1.13秒），含合成HTTP随机分包/EOS、三模式屏障、连续能量门、
取消与同编码器复用、收据/监听所有权模拟、失败不补跑、父进程总时限及每次请求时限。
其中真实HTTP+现装CPU Opus测试仅连接自有随机端口，三模式各收到3361个PCM样本、解码3个60ms帧，
子进程确认torch未导入；所有音频只在内存。独立新进程的计划检查确认12次测量、总16次上限、无网络、无torch。
严格文档检查退出1：新增记录未登记，报 unlisted-document/unknown-selection，实际检查0份；
不能宣称严格检查通过，清单由主会话整合登记。本轮不据模拟测试宣称Windows真实GPU资源核查已验收。

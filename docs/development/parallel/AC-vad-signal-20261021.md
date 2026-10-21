# AC：播放期输入信号的最小数值观测

2026-10-21；基线 `edc51f8b5b8ff669c1aa4d354f0ca436016de5da`；分支 `codex/ac-vad-signal-20261021`。ROOT 转述 buffered 实机复测仍无打断；授权仅实现无音频/正文的边界观测。未操作日用服务、私有配置、个人库、设备、串口、GPU 或网络，不调整 AEC、VAD、阈值、ASR、Smart Turn 或预生成。主会话另安排 AD 复核 AEC 合成风险，本任务不重复该实验。

## 安装与读取

[voice_vad_signal_observation.py](../../../scripts/development/xiaozhi/voice_vad_signal_observation.py) 使用标准库，导入不安装、不创建状态。在全部既有包装（含 direct_ws_v2）和 input observation 完成后调用，AI 负责启动器与控制端接线：

```python
from voice_vad_signal_observation import (
    install_voice_vad_signal_observation,
    voice_vad_signal_snapshot,
)
install_voice_vad_signal_observation(ConnectionHandler)
value = voice_vad_signal_snapshot(connection)
# 亦可读取 ConnectionHandler._longmemory_voice_vad_signal_snapshot(connection)
```

安装幂等，必须先安装 `voice_input_observation`。包装现有 `_ObservedVAD.is_vad`，不再在连接上叠第二层 VAD 代理，因此旧 `vad_check` 不会翻倍。原解码、AEC、VAD、session.run 各委托一次；共享 session 通过 ContextVar（上下文变量）归属本次连接。推理结果对象原样返回，不复制音频/张量；不新增推理、任务、线程或定时器。尚未接线/部署，代码检查不能代替实机验收。

## 固定 schema（版本 1）

顶层 `version/state/groups/recent_groups/count_keys/contract/aec_reference/window_positive_count/probability_bin_edges/value_kind`。`state` 为 `no_connection/not_observed/unavailable/observed`；前三种的 groups、contract 等为 null，不能解释为零输入。无连接的 getter 不创建状态。

- `groups`：按 `speaking/not_speaking/unknown` 固定分组的连接内累计汇总；播放状态取调用时的 `client_is_speaking`。
- `recent_groups`：同样三个分组，合并单调时钟当前秒与前两秒；最多三个内部合并桶，不导出秒编号、时间戳或逐帧序列。空窗口的 counts 全为 null，energy 空，probability null。
- 每组 `counts`：21 个定长值，按顶层 `count_keys` 的公开顺序解码：`dict(zip(value['count_keys'], group['counts']))`。未曾观察的事件为 null，已观察计数饱和于 `2**31-1`；达到上限后只能解释为至少该数值。
- 21 个事件依次为 `decode_return/aec_input/aec_output/vad_input/vad_true/vad_false/vad_none/vad_other/vad_raised/inference_return/inference_error/inference_contract_other/inference_observation_error/probability_invalid/probability_ge_high/probability_le_low/session_not_supported/decode_return_error/aec_output_error/aec_timestamp_nonzero_yes/aec_reference_present_yes`。
- `energy` 的键仅 `decode_return/aec_input/aec_output/vad_input`；未出现阶段不造零。累计值为 `max_rms_pcm16/last_rms_pcm16/max_peak_pcm16`，近期值只有 `max_rms_pcm16`。PCM 为16位小端单声道；只导出数值，计算后丢弃临时数组。`decode_return` 是安装时既有解码包装的返回值，直连 protocol 2 中可能已经过 AEC；真正的服务器 AEC 前后分别为 `aec_input/aec_output`。不能将 decode_return 错称为 AEC 前值。
- 累计 `probability` 为 `bins/min/max`；bins 七格，边界为顶层 `[0.01,0.1,0.2,0.5,0.8,0.95]`，区间左闭右开，最后格含1；近期只给 `min/max/count`。只观察原次 run 的输出，不额外推理；未取得合法概率为 null。`inference_return` 计原 run 成功返回；观测解析失败另计 `inference_observation_error`。
- `contract` 为实际加载对象的 `session_observed/threshold/threshold_low/silence_threshold_ms/frame_window_threshold/runtime_model_hash`。无法证明当前对象模型文件指纹，`runtime_model_hash` 明确 null。不读取 YAML。session 输入合同检查为 `input(1,576)/state(2,1,128)/sr16000`；不符另计数，不改变原输入。
- `aec_reference` 仅最近一次 AEC 调用的 `timestamp_nonzero/reference_present/nearest_reference_abs_delta_ms/reference_count`；时差按32位环形时间戳计算绝对最短距离，包含回绕；不导出时间戳或参考字节。参考缓存无效/读取失败为 null。它不证明被算法实际选中的参考、相关性或语音波形质量。
- `window_positive_count` 仅最后一次 VAD 调用后窗口内布尔 True 数量，最大100，不导出窗口序列。

固定 Silero 内部捕获异常后可能返回 None，旧 observer 的 `vad_error=0` 不能排除此情况；新 `vad_none` 和 session `inference_error` 分开保留，绝不转为 False 或重试。能量强不能证明是人声；解码后能量弱也不能证明设备 AEC 故障或所有者那一刻确实说话。仍需带所有者口令时段标记的实机复测才能判断本次根因。

## 有界性与验证

[单元测试](../../../tests/unit/development/test_voice_vad_signal_observation.py) 覆盖精确固定 Silero 控制流、原输入计数不翻倍、None/内部吞异常、无推理路径、v1 无 AEC 与已包装 v2 的 AEC 前后、回绕20ms、原异常身份、观察失败、共享 session/连接隔离、近期过期、独立快照、计数饱和及全部状态最大值。全状态、全事件饱和、极端合法数值的默认 JSON 序列化小于6000字节。ROOT/AI 后续确认原 device 最坏值已有15519字节，决定由 AI 在原8766控制服务、原Bearer鉴权下增加独立只读诊断响应；不将新对象塞入原 device 或8767投影，不新开端口、不增加原响应上限。端点与消费者验证由 AI 交付，本分支不宣称接线已完成。

固定源 fixture [xiaozhi_silero_snapshot_eb4b28c.py](../../../tests/fixtures/xiaozhi_silero_snapshot_eb4b28c.py) 仅提取 MIT 上游类，提交 `eb4b28c59ed7ed885258498cf757ce14352d620e`，原文件 SHA256 `aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114`；测试注入依赖，不导入外部应用或私有配置。

已执行主 Python 3.12 的新模块、旧输入观测、直连 v2 定向测试：39项通过。现有 CosyVoice 隔离 Python 3.10.20、ORT1.18.0、仅 CPUExecutionProvider，以已有6条 HuihuiDesktop 合成中文 WAV 各在播放/非播放状态复放：12场景、626包、1170次推理；原返回值、RNN（循环状态）、上下文、残留缓冲、五格窗口逐包一致。禁用 CUDA/Torch/TF/Flax 并确认未导入 Torch；无下载、真实音频或运行服务。模型 SHA256 `2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f`；合成输入 manifest SHA256 `adb42e113996d7bd90c3a2dcb68e73bbfee87f6a1446d61952378ac10e229ddc`。

本次本机 VAD 单包耗时 P50 0.2272→0.3864ms，P95 0.3589→0.5797ms；仅包含 VAD 输入能量/原推理观测，不包含另外三处解码/AEC能量，也不是端到端延迟或自然语音准确率。合成素材单声线、已见样本，不是盲测。未证明真实设备的 VAD 概率、AEC 抑制、声音或打断已恢复。

共享启动器、device_control、文档清单与公共指南仍由 AI 负责，不在本分支编辑。收尾由 ROOT 安排审查、整合与实机复测；本会话只提交自己的分支，不 merge、不 push、不向其他会话发消息。

# AC：公开语音的有界 CPU AEC/VAD 重放

2026-10-22。基线 `7f170ff136f52079552c28f678126e7092340854`，分支 `codex/ac-public-aec-replay-20261022`，实现提交 `e6c37372554321427f168fdf4a21371bbbd8108d`。旧 SmartTurn、融合、标记门禁分支及忽略产物保留。本轮仅公开夹具、合成混合及既有 CPU 模型；无个人声样、日用请求、下载/安装、GPU、新模型、录音、配置/个人库/固件/串口操作，不修改生产 AEC/VAD 算法或阈值。

实现为 [public_aec_replay.py](../../../scripts/development/xiaozhi/public_aec_replay.py)，边界回归为 [test_public_aec_replay.py](../../../tests/unit/development/test_public_aec_replay.py)。这是一次受控诊断，不是语音质量基准、口令识别率或现场根因证明。AI 后续只读审查，主会话安排整合；本会话不 merge、不 push、不向其他会话发消息。

## 固定来源与协议

- 官方 CosyVoice 固定 HEAD `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，两夹具均逐字节核对 Git 对象与磁盘，再复制进本次独占目录。`asset/zero_shot_prompt.wav` 为IEEE FLOAT、24kHz、单声道、83520帧/3.48秒，SHA256 `c7b31d6dbe7cc6a716dded00550db5b50940bf209e424e4ad207b12e657c8ff6`；`cross_lingual_prompt.wav` 为PCM16、22050Hz、单声道、303180帧，SHA256 `353a7715c2e4811f4045658b29d1ce67ecad5120e09de10ce890f1763aab486c`。用已有soundfile解码，未将浮点WAV误判为坏文件。
- 小智固定 HEAD `eb4b28c59ed7ed885258498cf757ce14352d620e`；原`connection.py` SHA256 `e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa`，原Silero源码SHA256 `aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114`。读取固定函数AST，不导入应用、ASR、LLM、TTS或私有配置。
- 既有Silero ONNX文件SHA256 `2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f`，显式只用CPUExecutionProvider。这证明本次文件与会话，不证明日用进程内模型指纹；线上观测此前该字段仍null。
- `resample_poly`分别用2/3、320/441，Kaiser 5.0/constant padding转16k；不逐帧AGC。两素材使用同一固定全片缩放0.801873452039953，使最大幅值为0.8，之后以32767缩放、rint转PCM16LE；越界/非有限输入拒绝，不用clip掩盖混合削波。
- 近端取zero-shot全3.48秒，前置0.6秒静默，尾部补至6秒；远端取cross-lingual前6.12秒。近端增益0.45、合成回声增益0.55，双讲为两者线性相加。每场景100个960样本/60ms包，参考按发送提前2帧逐步加入缓存，不整段预装；正序固定时间戳从1000000ms起。偏移场景只将传给AEC的时间戳加120ms，输入混合PCM字节不变。
- 原VAD每512样本推理、64样本context、五格需三格；显式使用已观测的0.5/0.3、600ms，场景/分支各自新连接初始化。每包用相同合成60ms时钟；出现句尾后调用固定原reset_audio_states，保留原RNN/context生命周期，不模拟ASR模型耗时。

参考观测在固定`aligned_ref`截取/补齐分支之后插入唯一只读回调；反向删除该AST节点必须还原原函数，逐包再核对原函数与插桩函数的输出字节一致。回调取得该次局部best_ts与aligned_ref，非事后查最近缓存、非第二次推断参考。trace记录实际参考帧索引和PCM SHA256，并核对等于该次实际缓存切片；无实际选参则null。

## 边界与执行记录

父进程全程120秒硬超时预算，预检占用会从剩余预算扣除；worker子进程额外至多90秒，逐包检查单调/CPU预算。科学计算导入前限制CPU线程、禁CUDA/Torch/TF/Flax、启离线；异常即停止该次运行并保全目录，不自动重试。输出必须在本工作树data/test-tmp下独占新建，所有文件用x/xb，既有产物不覆盖。

首轮`ac-public-aec-replay-20261022-60bf6db7/summary.json`为失败收据，SHA256 `91a163a7410fc9bf1ea606bd3417620be3096a598178b1874b09eb591a57736f`。1.531秒停止：harness模拟连接漏了原reset需要的logger，属于模拟接口缺失，非模型或AEC失败。按源码补齐logger/TAG并加入reset回归，验证普通缓冲清空而RNN/context保留。未改增益/场景/阈值；两次config去掉harness SHA后逐项一致。失败目录未改写。

成功结果的准确路径相对主项目实体根如下（本地忽略证据，不提交原WAV/实验产物）：

```text
local/worktrees/ac-smart-turn-20261021/data/test-tmp/ac-public-aec-replay-20261022-d30969fd/summary.json
```

- summary SHA256：`4b538ed63bf5f4fc20b36e194bdc4372d3f6a3e3e330f73234a42e77376ce3dd`。
- config SHA256：`f69cfbdd1c28f75768b9495197fffc9e6b53068f6b9bd25fe4142a4eb5d235dc`。
- 当前实现与产物`sources/harness.py`同SHA256：`f5bae9147f166368d070c4c91fd290077a21964668e6a200701a21f3f6f84932`。
- 转换后的`near_16k_timeline.wav` SHA256 `539f23c0f39e2017eafa5997401aad08015305e27cda4735593d9c0e4182627f`；`far_16k_reference.wav` SHA256 `6bd39bf78fb378f5329315f7a3807781355b1241a9f9e72215e54c860fb6152d`。每个case另含input/processed WAV及100行trace，逐项摘要在summary；selected帧可按far参考文件和索引重建，无需用假零拼接参考音频。

成功父进程耗时1.453秒；worker实际计算wall 0.532秒、CPU 0.5秒（不含其导入阶段，导入仍受父超时约束）。现有numpy1.26.4、scipy1.15.3、soundfile0.14.0、ORT1.20.1；仅CPU，无Torch导入、上游warning=0。未进行Opus往返，不声称覆盖设备编码/网络链路。

## 本次结果

每场景均100个60ms包。以下是VAD返回True的包数，不能读成识别率或近端召回率。

| 对照 | 输入→AEC后阳性包 | 输入→输出整段RMS |
|---|---:|---:|
| 近端单独，无参考 | 46→46 | 652.976→652.976 |
| 仅回声，参考对齐 | 79→43 | 1156.056→24.312 |
| 双讲，对齐时间戳 | 87→15 | 1324.301→271.996 |
| 同一双讲，时间戳+120ms | 87→19 | 1324.301→308.387 |
| 近端单独＋无关参考 | 46→42 | 652.976→358.933 |

500包全部通过原函数/插桩输出字节一致核对；共282次实际选参的切片哈希核对成立。近端阳性基线通过，模型/格式在本素材上不是全失效；回声显著降能后仍有43包阳性，不能凭低RMS直接认定无人声。双讲处理明显改变本素材VAD结果；但raw双讲阳性本身也含远端贡献，不能把87→15或素材时间区间58→14直接当作近端召回损失。

对齐双讲83次选参中相对已知回声源的帧偏移为0:66、-2:4、+2:4、-1:7、+1:2；时间戳+120ms时81次为0:72、+2:6、+1:3。输入SHA相同而输出及候选窗口改变，说明时间戳/参考选择值得审查；不证明偏移+120ms更正确或可修现场。选中不同帧可能是当前对数谱匹配规则的结果，不自动等于实现bug。

trace中的near_source_coverage及对应统计仅表示固定0.6–4.08秒模板时间区间，含原素材停顿；echo_only无近端时也可在该时间段有远端声音，不能将该字段当逐帧人声标签。无echo场景的reference offset只相对当前时间索引，不表示存在真实回声。分支句尾/reset不同可能清掉不同残余包，故输入/输出推理次数186/187略有差异；未强行对齐或丢弃以凑相等。

## 验证与后续边界

七项纯合成边界测试通过：真实所选局部参考、插桩透明性、未知源形状拒绝、非有限/削波拒绝、独占写入、固定场景与超预算拒绝、原reset接口与RNN生命周期。实际CPU重放另完成上述五对照；远程CI、真人、声场、固件AEC、丢包/抖动、完整Opus及正式ASR均未验收。

建议AI先审查原算法在这些受控输入下的近端保护、候选窗口与状态解释；任何候选修复都须同时保留仅回声负对照，不能用更多VAD阳性或更小RMS单指标判断更好。本分支不改时间戳、阈值或默认绕过AEC。是否需要≤5秒真人音频留给主会话在本次离线审查之后判断，未授权不得采集；本结果既不能替代现场，也不使录音自动成为必要步骤。

共享manifest/主指南留主会话或AI整合登记，本分支仅交自身harness、测试和窄记录。已执行严格文档检查，因本新增路径尚未登记而报unlisted-document/unknown-selection退出，不能据此声称文档验证通过；本地源码链接另核对存在。CLI需显式给出已有模型、两个vendor根及本工作树下的新output目录；不自动补依赖或换源。

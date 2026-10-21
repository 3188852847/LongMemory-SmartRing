# AD：固定上游完整WAV回退的交付回归与空返回修复

日期：2026-10-21。分支 `codex/ad-incremental-candidate-20261021`，本轮起点
`e31a288fe93be8d31e4fb256ce1d4da25719f02c`。本轮单独提交音频路径修复与固定SDK真实WAV/CPU Opus测试，
不改13字段状态契约、日用、配置、个人库或串口，不运行模型/GPU，不请求实机。

## AI回执与版本边界

只读核对AI回执：
`local/worktrees/ai-integration-review-20261021/data/test-tmp/ai-ad-full-wav-fallback-handoff-repro-01.json`。
它记录正常回退已交付却handoff=false，以及回调入队后抛错导致5次合成、5个重复包，最后仍fallback/before_handoff。
该回执没有提交号，不能直接绑定当前代码。

本分支此前afdb6734已补回退回调的handoff标记，84ac8cfc已截住回调错误的可重试信号。
本次只读看到AI树HEAD `aca7b9111b6d48a0a4d2402fa84978def0c83ebd`，其源码也已包含这两个分支；
这不替代独立回归。此前测试采用等价重试替身，原42项结果不作为本次缺口已覆盖的证据。

## 固定SDK原样回归与本次修复

[新夹具](../../../tests/fixtures/ad_full_wav_fallback_probe.py)从固定Git对象
`eb4b28c59ed7ed885258498cf757ce14352d620e` 原样提取：

- TTSProviderBase.to_tts_stream，明确运行delete_audio_file=True分支；
- audio_bytes_to_data_stream、pcm_to_data_stream两个转换函数。

不导入完整上游应用；生成函数为返回合成WAV/空/异常的明确异步替身。
真实pydub处理内存PCM16 WAV，现装Opus编码和解码，180ms/24kHz单声道音频正常为3个60ms帧。
流接口故意在交付前报合成异常，进入实际项目兼容回退路径；没有HTTP、模型调用或音频产物保存。

固定上游合成/解码失败耗尽5次后会直接return None，不抛异常。
本次原样回归发现：回调抛错场景在此前修正下已不重试，但“始终没有回调”仍被本层记为fallback。
[音频路径](../../../scripts/development/xiaozhi/cosyvoice_streaming.py)现增加固定分支：
非取消、兼容方法返回且handoff仍false时，结果为failed/before_handoff，清理编码器，不增加新的委托或请求。

此前已有的“交付前失败后允许下一片段buffered”“已开始回调不整段重播”“正常取消丢弃尾回调”继续保留。
不会把上游日志中的“生成成功”当作完整交付证明，也不把fallback计数用来代替completed。

## 八个精确场景

| 场景 | 合成替身调用 | 实际音频回调包 | handoff | last_outcome / failure_code |
|---|---:|---:|---|---|
| 正常完整WAV回退 | 1 | 3，解码4320样本 | true | fallback / before_handoff（原流错误原因） |
| 第一个回调入队后抛错 | 1 | 1，解码1440样本 | true | failed / after_handoff |
| 完整WAV返回时已取消 | 1 | 0 | false | cancelled / before_handoff |
| 首回调后正常取消 | 1 | 1 | true | cancelled / before_handoff |
| 首回调设置取消并抛错 | 1 | 1 | true | cancelled / before_handoff |
| 生成始终返回空 | 5 | 0 | false | failed / before_handoff |
| 生成始终抛异常 | 5 | 0 | false | failed / before_handoff |
| 返回坏WAV，解码耗尽重试 | 5 | 0 | false | failed / before_handoff |

这里的1/5均为合成替身调用，不是真实模型/HTTP调用。
最后三例保留固定上游交付前重试语义，不能写成每段只有一次HTTP；它们没有交付任何包。
回调失败例没有5次重复，也不记fallback/completed成功。取消例不抛回可重试错误，尾包丢弃。

新回执包含checkout_head、checkout_dirty与被测cosyvoice_streaming.py字节SHA256，
避免只给无版本的计数。最终干净提交后的回执路径随交付列明。

## 验证与交付边界

[新测试](../../../tests/unit/development/test_ad_full_wav_fallback.py)8项，加受影响策略/原流式分支共46项通过，1.08秒。
没有调用先前42项结果来覆盖新路径；未重跑无关全双工/GPU窗口或广泛CI。
策略模块未改，13键/固定枚举/计数饱和与505字节保守上界保持；相关有界schema测试同批通过。

```powershell
Set-Location -LiteralPath 'D:/03-项目/01-正式项目/智慧圆屏/local/worktrees/ad-cosy-continuity-20261021'
& 'D:/03-项目/01-正式项目/智慧圆屏/.venv/Scripts/python.exe' -B -X utf8 -m pytest tests/unit/development/test_ad_full_wav_fallback.py tests/unit/development/test_cosyvoice_delivery_candidate.py tests/unit/development/test_cosyvoice_streaming.py -q
```

ROOT→AI应按实际组合树运行上述固定SDK回归，并同时包含afdb6734/84ac8cfc已有修正及本次空返回修复；
若组合树已有前两项，直接审查本次增量即可。不自行向AI发消息、不合主/推送；文档清单由AI整合。
本次只闭合回退交付证据，不表示日用漏检、增量声学体验或真机验收已解决。
三处文件链接存在，差异检查通过；严格文档检查因未登记退出1、unknown-selection，实际检查0份，
另有本记录与前轮候选记录unlisted-document警告。共享manifest未改，登记由AI整合。

# Prompt 资源

Prompt 与代码分离并按用途、版本保存。首个 Fake LLM 闭环不依赖真实 Prompt。

`personas/`：圆屏人格候选文本，供手动替换小智私有配置的 prompt；不是自动加载的 Skill，也不进入用户记忆库。

- `elysia_v1.txt`：参考 elysia.skill 的爱莉希雅风格语音人格，保留事实/记忆边界。
- `plain_v1.txt`：普通助手回退候选，不是现有私有配置备份。

出处、MIT 声明、审查范围和启用方式见 `docs/third_party/elysia-skill-review.md`。资源当前由源码目录手动使用，不宣称 wheel 安装后自动携带或生效。角色效果和 TTS 听感尚未实测；普通 PC 评估不自动使用这些人格。

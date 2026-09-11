"""启动面板的纯显示决策；不依赖 Tk，也不管理任何进程。"""


def summary_text(
    voice,
    start_page,
    role,
    extraction,
    retrieval,
    tts,
    allow_delete,
    consolidation,
    memory_backend="longmemory",
    vad_profile="normal",
):
    """把内部启动枚举翻译为日常首页可理解的三行摘要。"""

    mode = "网页＋圆屏语音" if voice else "网页文字聊天"
    page_label = {
        "overview": "系统总览",
        "chat": "聊天",
        "device": "设备状态",
        "memories": "记忆管理",
        "settings": "设置中心",
    }[start_page]
    role_label = "爱莉希雅风格" if role == "elysia_v1" else "普通助手"
    extraction_label = "模型辅助提取" if extraction == "llm" else "规则提取"
    retrieval_label = (
        "关键词＋语义召回" if retrieval == "hybrid" else "关键词召回"
    )
    sound_label = {
        "edge": "EdgeTTS 联网声音",
        "voxcpm2": "VoxCPM2 本地声音",
        "sanotts": "sanoTTS 本地小雅",
    }[tts]
    delete_label = "允许单条删除" if allow_delete else "不开放删除"
    consolidation_label = "低频整理已开启" if consolidation else "低频整理关闭"
    backend_label = {
        "longmemory": "圆屏：LongMemory",
        "xiaozhi_local": "圆屏：小智本地摘要",
        "none": "圆屏：无长期记忆",
    }[memory_backend]
    vad_label = {
        "normal": "普通拾音",
        "noisy": "嘈杂环境拾音",
        "close_talk": "近讲严格拾音",
    }[vad_profile]
    return (
        f"{mode}  ·  打开{page_label}  ·  {role_label}\n"
        f"{extraction_label}  ·  {retrieval_label}  ·  "
        f"{sound_label}  ·  {vad_label}\n"
        f"{delete_label}  ·  {consolidation_label}  ·  {backend_label}"
    )


def failure_hint(exited):
    """把稳定退出码翻译为排障提示，不读取或复制子进程输出。"""

    hints = []
    for name, code in exited:
        if name == "console" and code == 2:
            hint = "控制台参数或本机配置未通过检查；先核对数据库、模型配置和高级设置"
        elif name == "voice" and code == 3:
            hint = "圆屏语音的共享路径或配置未通过检查；先核对小智目录、数据库和所选模型"
        elif name == "voice" and code == 4:
            hint = "VoxCPM2 在限定时间内未就绪；先核对声音环境、模型文件、CUDA 和 18768 端口"
        elif name == "voxcpm2":
            hint = "本地声音服务已退出；先核对声音环境、模型文件、CUDA 和 18768 端口"
        elif name == "sanotts":
            hint = "sanoTTS 已退出；先核对外部源码/中文模型、Node.js 和 18769 端口"
        elif name == "voice":
            hint = "圆屏语音进程意外退出；先核对小智配置、网络地址和 8000/8003/8766 端口"
        elif name == "console":
            hint = "网页控制台意外退出；先核对数据库、模型配置和 8767 端口"
        else:
            hint = f"{name} 组件意外退出；请打开使用指南核对该组件的本机配置"
        if hint not in hints:
            hints.append(hint)
    return "；".join(hints) + "。" if hints else "请打开使用指南核对本机配置。"

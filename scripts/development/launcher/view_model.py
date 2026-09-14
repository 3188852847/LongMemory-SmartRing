"""启动面板的纯显示决策；不依赖 Tk，也不管理任何进程。"""


def daily_recommendation():
    """返回已验收的日用组合；界面只负责把枚举映射到控件。"""
    return {
        "model_profile": "campus",
        "voice_model_profile": "campus",
        "memory_backend": "longmemory",
        "memory_extraction": "llm",
        "memory_retrieval": "hybrid",
        "tts_backend": "cosyvoice3",
        "vad_profile": "normal",
        "memory_consolidation": False,
        "l1_sufficiency_shadow": False,
        "l2_sufficiency_shadow": False,
    }


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
    l2_sufficiency_shadow=False,
    l1_sufficiency_shadow=False,
    model_profile="campus",
    voice_model_profile="campus",
):
    """把内部启动枚举翻译为按网页、圆屏和实验边界分行的摘要。"""

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
        "cosyvoice3": "CosyVoice 3 本地高质量声音",
    }[tts]
    delete_label = "允许单条删除" if allow_delete else "不开放删除"
    experimental = []
    if consolidation:
        experimental.append("低频整理")
    if l1_sufficiency_shadow:
        experimental.append("L1 旁路质检")
    if l2_sufficiency_shadow:
        experimental.append("L2 旁路质检")
    experimental_label = "、".join(experimental) + "已开启" if experimental else "均关闭"
    backend_label = {
        "longmemory": "LongMemory",
        "xiaozhi_local": "小智本地摘要",
        "none": "无长期记忆",
    }[memory_backend]
    vad_label = {
        "normal": "普通拾音",
        "noisy": "嘈杂环境拾音",
        "close_talk": "近讲严格拾音",
    }[vad_profile]
    web_model_label = "学校模型" if model_profile == "campus" else "官方 DeepSeek"
    voice_model_label = (
        "学校模型" if voice_model_profile == "campus" else "官方 DeepSeek"
    )
    round_screen = (
        f"圆屏：{voice_model_label}  ·  {backend_label}  ·  {sound_label}  ·  {vad_label}"
        if voice else f"圆屏：本次不启动  ·  下次声音 {sound_label}"
    )
    return (
        f"{mode}  ·  打开{page_label}  ·  {role_label}\n"
        f"网页：{web_model_label}  ·  {extraction_label}  ·  {retrieval_label}\n"
        f"{round_screen}\n"
        f"记忆管理：{delete_label}  ·  实验开关：{experimental_label}"
    )


def failure_hint(exited, tts_backend=None):
    """把稳定退出码翻译为排障提示，不读取或复制子进程输出。"""

    hints = []
    for name, code in exited:
        if name == "console" and code == 2:
            hint = "控制台参数或本机配置未通过检查；先核对数据库、模型配置和高级设置"
        elif name == "voice" and code == 3:
            hint = "圆屏语音的共享路径或配置未通过检查；先核对小智目录、数据库和所选模型"
        elif name == "voice" and code == 4:
            # 退出码 4 属于小智等待“当前本地 TTS”的通用门槛，不能继续用
            # 最早只有 VoxCPM2 时留下的固定文案误导用户排查错误端口。
            hint = {
                "voxcpm2": "VoxCPM2 在限定时间内未就绪；先核对声音环境、模型文件、CUDA 和 18768 端口",
                "sanotts": "sanoTTS 在限定时间内未就绪；先核对外部源码、Node.js 和 18769 端口",
                "cosyvoice3": "CosyVoice 3 在限定时间内未就绪；先核对独立环境、模型文件、CUDA 和 18770 端口",
            }.get(tts_backend, "所选本地声音在限定时间内未就绪；先核对声音后端环境和对应环回端口")
        elif name == "voxcpm2":
            hint = "本地声音服务已退出；先核对声音环境、模型文件、CUDA 和 18768 端口"
        elif name == "sanotts":
            hint = "sanoTTS 已退出；先核对外部源码/中文模型、Node.js 和 18769 端口"
        elif name == "cosyvoice3":
            hint = "CosyVoice 3 已退出；先核对独立环境、模型快照、CUDA 和 18770 端口"
        elif name == "voice":
            hint = "圆屏语音进程意外退出；先核对小智配置、网络地址和 8000/8003/8766 端口"
        elif name == "console":
            hint = "网页控制台意外退出；先核对数据库、模型配置和 8767 端口"
        else:
            hint = f"{name} 组件意外退出；请打开使用指南核对该组件的本机配置"
        if hint not in hints:
            hints.append(hint)
    return "；".join(hints) + "。" if hints else "请打开使用指南核对本机配置。"


def failed_services(exited, tts_backend=None):
    details = "、".join(f"{name}（退出码 {code}）" for name, code in exited)
    return {
        "components": {
            "console": ("启动失败", "error"),
            "voice": ("进程已停止", "error"),
            "speech": ("进程已停止", "error"),
            "browser": ("未打开", "error"),
        },
        "message": (
            f"服务已退出：{details}。已停止其他受管服务。"
            f"{failure_hint(exited, tts_backend)}"
        ),
        "tone": "error",
    }


def starting_services(*, voice, tts_backend, model_profile, voice_model_profile,
                      memory_backend):
    """生成启动阶段呈现；这里只翻译选项，不执行配置同步或启动进程。"""

    speech = {
        "edge": "EdgeTTS 已选择",
        "voxcpm2": "VoxCPM2 加载中",
        "sanotts": "sanoTTS 加载中",
        "cosyvoice3": "CosyVoice 3 加载并预热中",
    }[tts_backend]
    model_label = "官方 DeepSeek" if model_profile == "official" else "学校模型"
    voice_model_label = (
        "官方 DeepSeek" if voice_model_profile == "official" else "学校模型"
    )
    memory_label = {
        "longmemory": "LongMemory",
        "xiaozhi_local": "小智本地摘要",
        "none": "无长期记忆",
    }[memory_backend]
    voice_detail = (
        f"，圆屏使用 {voice_model_label} / {memory_label}。" if voice else "。"
    )
    return {
        "components": {
            "console": ("启动中", "busy"),
            "voice": ("启动中", "busy") if voice else ("本次未启用", "idle"),
            "speech": (speech, "busy") if voice else ("本次未启用", "idle"),
            "browser": ("等待控制台", "busy"),
        },
        "message": (
            f"正在启动；网页使用 {model_label}{voice_detail}"
            "语音模式已自动核对并备份同步配置；首次加载语音模型可能较慢。"
        ),
        "tone": "busy",
    }


def stopped_services():
    return {
        "components": {
            "console": ("已停止", "idle"),
            "voice": ("未启动", "idle"),
            "speech": ("未启动", "idle"),
            "browser": ("未打开", "idle"),
        },
        "message": "已停止本面板启动的服务；其他终端启动的程序未被停止。",
        "tone": "idle",
    }


def ready_services(*, voice, tts_backend, local_tts_ready, opened):
    """生成服务就绪视图；设备是否连接仍由网页实时状态负责。"""

    if voice and tts_backend in {"voxcpm2", "sanotts", "cosyvoice3"}:
        label = {"voxcpm2": "VoxCPM2", "sanotts": "sanoTTS",
                 "cosyvoice3": "CosyVoice 3"}[tts_backend]
        suffix = (
            f"；{label} 与语音进程运行中"
            if local_tts_ready
            else f"；{label} 正在加载，圆屏语音尚未就绪"
        )
        speech = (
            f"{label} 已就绪" if local_tts_ready else f"{label} 加载中",
            "good" if local_tts_ready else "busy",
        )
    else:
        suffix = "；语音进程运行中，设备连接请在网页查看" if voice else ""
        speech = ("EdgeTTS 已选择", "good") if voice else ("本次未启用", "idle")
    return {
        "components": {
            "console": ("已就绪", "good"),
            "voice": (
                "小智进程运行" if voice else "本次未启用",
                "good" if voice else "idle",
            ),
            "speech": speech,
            "browser": (
                "已请求打开" if opened else "尚未打开",
                "good" if opened else "busy",
            ),
        },
        "message": (
            "控制台已就绪" + suffix
            + "。请在聊天页查看或检测模型状态；关闭网页不会停止服务。"
        ),
        "tone": "good",
    }


def readiness_timeout():
    return {
        "components": {
            "console": ("就绪超时", "error"),
            "voice": ("进程已停止", "error"),
            "speech": ("进程已停止", "error"),
            "browser": ("未打开", "error"),
        },
        "message": (
            "90 秒内未确认控制台就绪，已停止受管服务；未停止其他程序。"
            "请查看指南。"
        ),
        "tone": "error",
    }

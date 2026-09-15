"""无新增依赖的 Windows 日常启动面板；服务生命周期属于这个窗口。"""

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from pathlib import Path

from runtime import (
    DEFAULT_BGE_MODEL, DEFAULT_SANOTTS_SOURCE, Manager, Options, ROOT, Singleton,
    VOICE_ROOT, console_url, doubao_config_module,
)
from network import local_addresses, config_action
from preferences import (
    DEFAULT_SESSION_ALLOW_MEMORY_DELETE,
    load_memory_backend,
    load_model_profile,
    load_preferences,
    load_tts_backend,
    save_memory_backend,
    save_model_profile,
    save_preferences,
    save_tts_backend,
)
from firewall_panel import open_panel
from control import CONTROL_FILE_NAME, LauncherControl
from tts import config_action as tts_config_action
from voice_recovery import close_stale_tts, close_stale_voice
from view_model import failure_hint as _failure_hint
from view_model import summary_text as _summary_text
from view_model import (
    daily_recommendation,
    failed_services,
    readiness_timeout,
    ready_services,
    starting_services,
    stopped_services,
)


# 启动器与网页控制台共享“克制未来科技”语义；Tk 不支持网页的渐变和
# 切角，因此只复用深海军蓝、青色主操作、琥珀警告和红色故障。
APP_BACKGROUND = "#050f1f"
CARD_BACKGROUND = "#09192c"
SURFACE_MUTED = "#0c2036"
ACCENT = "#28d7f2"
ACCENT_HOVER = "#66e8fa"
TEXT_STRONG = "#e8f7ff"
TEXT_MUTED = "#7fa5bb"
BORDER = "#1c4b69"
SUCCESS = "#38e5a3"
WARNING = "#ffbd4a"
DANGER = "#ff647c"


def open_web_search_configuration(parent):
    import sys
    directory = str(ROOT / "scripts/development/xiaozhi")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    from voice_web_settings import open_search_configuration
    return open_search_configuration(parent)


def open_doubao_configuration(parent, path, on_saved=None):
    """密钥只在用户打开的本机对话框中输入，不回填已保存密钥或写入偏好。"""
    dialog = tk.Toplevel(parent)
    dialog.title("豆包实时语音配置")
    dialog.transient(parent)
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=20)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="开通豆包实时语音服务后，填写该服务的 API Key。",
              wraplength=510).pack(anchor="w")
    ttk.Label(body, text="凭据仅保存到本机 .env.doubao.local；不会进行联网验证。",
              wraplength=510).pack(anchor="w", pady=(4, 12))
    secret = tk.StringVar(dialog, value="")
    ttk.Label(body, text="实时语音 API Key（已保存的内容不会回显）").pack(anchor="w")
    entry = ttk.Entry(body, textvariable=secret, show="●", width=65)
    entry.pack(fill="x", pady=(4, 12))
    status = tk.StringVar(dialog, value="未开通时可直接关闭，语音模式选择仍会保留。")
    ttk.Label(body, textvariable=status, wraplength=510).pack(anchor="w")

    def close():
        secret.set("")
        dialog.destroy()

    def save():
        try:
            doubao_config_module().save_credentials(path, api_key=secret.get().strip())
        except (OSError, ValueError):
            status.set("未能保存。请检查凭据是否完整、是否含换行，以及配置目录是否可写。")
            return
        secret.set("")
        if on_saved is not None:
            on_saved()
        dialog.destroy()

    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(16, 0))
    ttk.Button(buttons, text="保存到本机", command=save).pack(side="right")
    ttk.Button(buttons, text="关闭", command=close).pack(side="right", padx=8)
    dialog.protocol("WM_DELETE_WINDOW", close)
    entry.focus_set()
    dialog.grab_set()
    return dialog


def _scrollable_tab(parent):
    """创建可随窗口缩放并支持纵向滚动的页签内容区。

    启动选项会随产品迭代增加；把滚动能力放在页签容器层，可以保证小屏幕
    和 Windows 高缩放比例下仍能访问底部操作，而不要求每个设置分组自行处理。
    """
    shell = ttk.Frame(parent)
    canvas = tk.Canvas(
        shell,
        highlightthickness=0,
        borderwidth=0,
        background=APP_BACKGROUND,
    )
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
    content = ttk.Frame(canvas, padding=(22, 20), style="Page.TFrame")
    content_window = canvas.create_window((0, 0), window=content, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def update_scroll_region(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def match_content_width(event):
        # 纵向滚动时内容仍跟随可视宽度，避免额外出现横向滚动或右侧留白。
        canvas.itemconfigure(content_window, width=event.width)

    content.bind("<Configure>", update_scroll_region)
    canvas.bind("<Configure>", match_content_width)
    return shell, content, canvas


def _page_heading(parent, title, description):
    """给每个任务页提供稳定标题和用途说明，减少只靠页签猜测。"""
    block = ttk.Frame(parent, style="Page.TFrame")
    block.pack(fill="x", pady=(0, 14))
    ttk.Label(block, text=title, style="PageTitle.TLabel").pack(anchor="w")
    ttk.Label(
        block,
        text=description,
        style="Subtitle.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(3, 0))
    return block


def _boolean_option(
    parent,
    variable,
    *,
    title,
    description,
    enabled_text="已开启",
    disabled_text="已关闭",
):
    """用明确状态按钮代替主题相关的复选框字形。

    Windows 的 clam 主题会用 ``×`` 绘制已选中的 Checkbutton，容易被理解成
    禁用或错误。这里继续复用 BooleanVar，只把呈现改成标题、影响说明和实时状态。
    """

    row = ttk.Frame(parent, padding=(12, 9), style="Option.TFrame")
    copy = ttk.Frame(row, style="Option.TFrame")
    copy.pack(side="left", fill="x", expand=True)
    ttk.Label(copy, text=title, style="OptionTitle.TLabel").pack(anchor="w")
    ttk.Label(
        copy,
        text=description,
        wraplength=500,
        justify="left",
        style="OptionHint.TLabel",
    ).pack(anchor="w", pady=(2, 0))
    button = ttk.Button(row, width=10)
    button.pack(side="right", padx=(14, 0))

    def render(*_):
        enabled = bool(variable.get())
        button.configure(
            text=enabled_text if enabled else disabled_text,
            style="ToggleOn.TButton" if enabled else "ToggleOff.TButton",
        )

    button.configure(command=lambda: variable.set(not variable.get()))
    variable.trace_add("write", render)
    render()
    row.pack(fill="x", pady=(0, 6))
    return row, button


def main():
    window = tk.Tk()
    window.title("LongMemory · 日常启动")
    window.geometry("1040x800")
    window.minsize(760, 560)
    window.configure(background=APP_BACKGROUND)
    style = ttk.Style(window)
    # Clam 允许同一套颜色和间距在不同 Windows 主题下保持稳定；这里只
    # 改启动器自身的绘制，不影响系统主题或 React 控制台。
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("App.TFrame", background=APP_BACKGROUND)
    style.configure("Page.TFrame", background=APP_BACKGROUND)
    style.configure("Header.TFrame", background=APP_BACKGROUND)
    style.configure("Footer.TFrame", background=APP_BACKGROUND)
    style.configure("TFrame", background=APP_BACKGROUND)
    style.configure("TLabel", background=APP_BACKGROUND, foreground=TEXT_STRONG,
                    font=("Microsoft YaHei UI", 9))
    style.configure("Title.TLabel", background=APP_BACKGROUND, foreground=TEXT_STRONG,
                    font=("Microsoft YaHei UI", 22, "bold"))
    style.configure("PageTitle.TLabel", background=APP_BACKGROUND,
                    foreground=TEXT_STRONG, font=("Microsoft YaHei UI", 14, "bold"))
    style.configure("Card.TFrame", background=CARD_BACKGROUND)
    style.configure("CardSelection.TLabel", background=CARD_BACKGROUND,
                    foreground=ACCENT, font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("CardHint.TLabel", background=CARD_BACKGROUND,
                    foreground=TEXT_MUTED, font=("Microsoft YaHei UI", 9))
    style.configure("Eyebrow.TLabel", foreground=ACCENT, font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("Subtitle.TLabel", foreground=TEXT_MUTED)
    style.configure("Hint.TLabel", foreground=TEXT_MUTED, font=("Microsoft YaHei UI", 9))
    style.configure("Summary.TLabel", font=("Microsoft YaHei UI", 10), foreground=TEXT_STRONG)
    style.configure("Meta.TLabel", foreground=TEXT_MUTED, background=SURFACE_MUTED,
                    font=("Microsoft YaHei UI", 8), padding=(10, 5))
    style.configure("StatusIdle.TLabel", foreground=TEXT_MUTED, font=("Microsoft YaHei UI", 12))
    style.configure("StatusBusy.TLabel", foreground=WARNING, font=("Microsoft YaHei UI", 12))
    style.configure("StatusGood.TLabel", foreground=SUCCESS, font=("Microsoft YaHei UI", 12))
    style.configure("StatusError.TLabel", foreground=DANGER, font=("Microsoft YaHei UI", 12))
    style.configure("StatusCell.TFrame", background=SURFACE_MUTED, borderwidth=1,
                    relief="solid")
    style.configure("StatusCellTitle.TLabel", background=SURFACE_MUTED,
                    foreground=TEXT_MUTED, font=("Microsoft YaHei UI", 8))
    style.configure("StatusCellValue.TLabel", background=SURFACE_MUTED,
                    foreground=TEXT_STRONG, font=("Microsoft YaHei UI", 9, "bold"))
    for name, color in (("Idle", TEXT_MUTED), ("Busy", WARNING),
                        ("Good", SUCCESS), ("Error", DANGER)):
        style.configure(f"StatusCell{name}.TLabel", background=SURFACE_MUTED,
                        foreground=color, font=("Microsoft YaHei UI", 11))
    style.configure("Primary.TButton", background=ACCENT, foreground="#03101d",
                    bordercolor=ACCENT, font=("Microsoft YaHei UI", 10, "bold"), padding=(18, 10))
    style.map("Primary.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#174052")],
              foreground=[("disabled", TEXT_MUTED)])
    style.configure("Secondary.TButton", background=CARD_BACKGROUND, foreground=TEXT_STRONG,
                    bordercolor=BORDER, padding=(12, 9))
    style.map("Secondary.TButton", background=[("active", SURFACE_MUTED)])
    style.configure("TEntry", fieldbackground=SURFACE_MUTED, foreground=TEXT_STRONG,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TCombobox", fieldbackground=SURFACE_MUTED, background=SURFACE_MUTED,
                    foreground=TEXT_STRONG, bordercolor=BORDER, arrowcolor=ACCENT)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE_MUTED)],
              foreground=[("readonly", TEXT_STRONG)],
              selectbackground=[("readonly", SURFACE_MUTED)],
              selectforeground=[("readonly", TEXT_STRONG)])
    style.configure("TRadiobutton", background=APP_BACKGROUND, foreground=TEXT_STRONG,
                    indicatorcolor=SURFACE_MUTED, focuscolor=ACCENT)
    style.configure("TCheckbutton", background=APP_BACKGROUND, foreground=TEXT_STRONG,
                    indicatorcolor=SURFACE_MUTED, focuscolor=ACCENT)
    style.map("TRadiobutton", indicatorcolor=[("selected", ACCENT)])
    style.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)])
    style.configure("Option.TFrame", background=SURFACE_MUTED, borderwidth=1,
                    relief="solid")
    style.configure("OptionTitle.TLabel", background=SURFACE_MUTED,
                    foreground=TEXT_STRONG, font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("OptionHint.TLabel", background=SURFACE_MUTED,
                    foreground=TEXT_MUTED, font=("Microsoft YaHei UI", 8))
    style.configure("Selection.TLabel", foreground=ACCENT,
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("Save.TFrame", background=SURFACE_MUTED, borderwidth=1,
                    relief="solid")
    style.configure("Save.TLabel", background=SURFACE_MUTED, foreground=SUCCESS,
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("SaveError.TLabel", background=SURFACE_MUTED, foreground=DANGER,
                    font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("WarningHint.TLabel", background=CARD_BACKGROUND,
                    foreground=WARNING, font=("Microsoft YaHei UI", 9))
    style.configure("ToggleOn.TButton", background="#0d5a47", foreground=TEXT_STRONG,
                    bordercolor=SUCCESS, font=("Microsoft YaHei UI", 9, "bold"),
                    padding=(10, 7))
    style.map("ToggleOn.TButton", background=[("active", "#11725a")],
              foreground=[("disabled", TEXT_MUTED)])
    style.configure("ToggleOff.TButton", background=CARD_BACKGROUND,
                    foreground=TEXT_MUTED, bordercolor=BORDER,
                    font=("Microsoft YaHei UI", 9), padding=(10, 7))
    style.map("ToggleOff.TButton", background=[("active", "#10304a")],
              foreground=[("disabled", TEXT_MUTED)])
    style.configure("TScrollbar", background=SURFACE_MUTED, troughcolor=APP_BACKGROUND,
                    bordercolor=BORDER, arrowcolor=TEXT_MUTED)
    style.configure("Section.TLabelframe", padding=16, background=CARD_BACKGROUND,
                    bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("Section.TLabelframe.Label", background=APP_BACKGROUND,
                    foreground=TEXT_STRONG, font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TNotebook", background=APP_BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 10))
    style.configure("TNotebook.Tab", background=SURFACE_MUTED, foreground=TEXT_MUTED,
                    font=("Microsoft YaHei UI", 9), padding=(18, 9))
    style.map("TNotebook.Tab", background=[("selected", CARD_BACKGROUND), ("active", "#10304a")],
              foreground=[("selected", ACCENT)])
    try:
        lock = Singleton()
    except ValueError as error:
        window.withdraw()
        messagebox.showinfo("已有启动面板或端口占用", str(error))
        window.destroy()
        return
    manager = Manager()
    box = ttk.Frame(window, padding=(28, 22), style="App.TFrame")
    box.pack(fill="both", expand=True)
    choice_path = ROOT / 'data/control/launcher.json'
    model_profile_path = ROOT / 'data/control/model-profile.json'
    memory_backend_path = ROOT / 'data/control/memory-backend.json'
    tts_backend_path = ROOT / 'data/control/tts-backend.json'
    control = LauncherControl(lock.socket, ROOT / 'data/control' / CONTROL_FILE_NAME)
    saved = load_preferences(choice_path)
    saved["tts_backend"] = load_tts_backend(tts_backend_path, saved["tts_backend"])
    header = ttk.Frame(box, style="Header.TFrame")
    header.pack(fill="x", pady=(0, 18))
    header_copy = ttk.Frame(header, style="Header.TFrame")
    header_copy.pack(side="left", fill="x", expand=True)
    ttk.Label(header_copy, text="个人陪伴控制台", style="Eyebrow.TLabel").pack(anchor="w")
    ttk.Label(header_copy, text="LongMemory", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        header_copy,
        text="启动一次，就可以使用文字聊天和 SmartRing-Plus 圆屏；常用选择保存在本机。",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(3, 0))
    ttk.Label(header, text="本机启动器 · 不接管外部进程", style="Meta.TLabel").pack(side="right", anchor="n")
    tabs = ttk.Notebook(box)
    tabs.pack(fill="both", expand=True)
    daily_tab, daily, daily_canvas = _scrollable_tab(tabs)
    intelligence_tab, intelligence, intelligence_canvas = _scrollable_tab(tabs)
    device_tab, device, device_canvas = _scrollable_tab(tabs)
    maintenance_tab, maintenance, maintenance_canvas = _scrollable_tab(tabs)
    tabs.add(daily_tab, text="日常启动")
    tabs.add(intelligence_tab, text="模型与记忆")
    tabs.add(device_tab, text="圆屏与声音")
    tabs.add(maintenance_tab, text="本机维护")
    canvases = (daily_canvas, intelligence_canvas, device_canvas, maintenance_canvas)
    # 高频操作固定在页签外。窗口变矮或高级设置内容较长时，用户依然可以
    # 立即启动、停止或重新打开网页，不必先滚动到页面末尾。
    footer = ttk.Frame(box, style="Footer.TFrame")
    footer.pack(fill="x", pady=(14, 0))

    def scroll_current_tab(event):
        """鼠标位于面板任意控件上时，滚动当前可见页签。"""
        canvas = canvases[tabs.index("current")]
        if not event.delta:
            return
        units = -int(event.delta / 120)
        canvas.yview_scroll(units if units else (-1 if event.delta > 0 else 1), "units")

    window.bind_all("<MouseWheel>", scroll_current_tab, add="+")

    voice = tk.BooleanVar(value=saved["voice"])
    voice_mode_labels = {"现有语音链路": "pipeline", "豆包实时语音（备用）": "doubao_realtime"}
    voice_mode = tk.StringVar(value=next(
        label for label, value in voice_mode_labels.items() if value == saved["voice_mode"]
    ))
    voice_latency_labels = {"实时优先": "realtime", "原策略（对照）": "original"}
    voice_latency_mode = tk.StringVar(value=next(
        label for label, value in voice_latency_labels.items() if value == saved["voice_latency_mode"]
    ))
    start_page_labels = {"系统总览": "overview", "聊天": "chat", "设备状态": "device", "记忆管理": "memories", "设置中心": "settings"}
    start_page = tk.StringVar(value=next(label for label, value in start_page_labels.items() if value == saved["start_page"]))
    consent = tk.BooleanVar(value=saved["http_risk_ack"])
    database = tk.StringVar(value=saved["database"] or str(ROOT / "data/databases/xiaozhi-demo-v1.db"))
    server = tk.StringVar(value=saved["voice_root"] or str(VOICE_ROOT))
    ip = tk.StringVar(value=saved["lan_ip"])
    role_labels = {"爱莉希雅风格": "elysia_v1", "普通助手": "plain_v1"}
    role = tk.StringVar(value=next(
        label for label, value in role_labels.items() if value == saved["role"]
    ))
    extraction_labels = {"rules": "规则提取（基础/对照）", "llm": "模型辅助提取（日常推荐）"}
    retrieval_labels = {"keyword": "关键词召回（基础/对照）", "hybrid": "关键词＋BGE 混合召回（日常推荐）"}
    tts_labels = {
        "edge": "EdgeTTS（联网稳定回退）",
        "voxcpm2": "VoxCPM2（本地 plain）",
        "sanotts": "sanoTTS（实验速度基线，音质较低）",
        "cosyvoice3": "CosyVoice 3（本地高质量，日常推荐）",
    }
    memory_extraction = tk.StringVar(value=extraction_labels[saved["memory_extraction"]])
    memory_retrieval = tk.StringVar(value=retrieval_labels[saved["memory_retrieval"]])
    allow_memory_delete = tk.BooleanVar(value=DEFAULT_SESSION_ALLOW_MEMORY_DELETE)
    memory_consolidation = tk.BooleanVar(value=saved["memory_consolidation"])
    l1_sufficiency_shadow = tk.BooleanVar(
        value=saved["l1_sufficiency_shadow"]
    )
    l2_sufficiency_shadow = tk.BooleanVar(
        value=saved["l2_sufficiency_shadow"]
    )
    embedding_model = tk.StringVar(value=saved["embedding_model_dir"] or str(DEFAULT_BGE_MODEL))
    tts_backend = tk.StringVar(value=tts_labels[saved["tts_backend"]])
    # 记录面板最后一次从共享指针吸收的值。启动前只有在用户没有亲自改过
    # 下拉框时才重新读取网页选择，避免已打开的面板覆盖控制台的新意图。
    tts_pointer_seen = {"backend": saved["tts_backend"]}
    sanotts_source = tk.StringVar(
        value=saved["sanotts_source_root"] or str(DEFAULT_SANOTTS_SOURCE)
    )
    vad_profile_labels = {
        "普通环境（标准灵敏度）": "normal",
        "嘈杂环境（过滤较远人声）": "noisy",
        "近讲严格（需靠近圆屏）": "close_talk",
    }
    vad_profile = tk.StringVar(value=next(
        label for label, value in vad_profile_labels.items()
        if value == saved["vad_profile"]
    ))
    model_profile_labels = {"学校模型（校园网）": "campus", "官方 DeepSeek（公网 HTTPS）": "official"}
    active_model_profile = load_model_profile(model_profile_path, "web")
    model_profile = tk.StringVar(value=next(label for label, value in model_profile_labels.items()
                                             if value == active_model_profile))
    active_voice_model_profile = load_model_profile(model_profile_path, "voice")
    voice_model_profile = tk.StringVar(value=next(label for label, value in model_profile_labels.items()
                                                   if value == active_voice_model_profile))
    model_pointer_seen = {
        "web": active_model_profile,
        "voice": active_voice_model_profile,
    }
    memory_backend_labels = {
        "LongMemory（分层、可追溯）": "longmemory",
        "小智本地摘要（轻量对照）": "xiaozhi_local",
        "无长期记忆（速度基线）": "none",
    }
    active_memory_backend = load_memory_backend(memory_backend_path)
    memory_backend = tk.StringVar(value=next(
        label for label, value in memory_backend_labels.items()
        if value == active_memory_backend
    ))
    memory_backend_pointer_seen = {"backend": active_memory_backend}

    def selected_model_profile():
        return model_profile_labels[model_profile.get()]

    def selected_role():
        return role_labels[role.get()]

    def selected_voice_model_profile():
        return model_profile_labels[voice_model_profile.get()]

    def selected_voice_mode():
        return voice_mode_labels[voice_mode.get()]

    def selected_voice_latency_mode():
        return voice_latency_labels[voice_latency_mode.get()]

    def selected_memory_backend():
        return memory_backend_labels[memory_backend.get()]

    def set_memory_backend(value):
        label = next((label for label, backend in memory_backend_labels.items()
                      if backend == value), None)
        if label is not None:
            memory_backend.set(label)

    def selected_extraction():
        return "llm" if memory_extraction.get().startswith("模型") else "rules"

    def selected_retrieval():
        return "hybrid" if "BGE" in memory_retrieval.get() else "keyword"

    def selected_tts():
        if tts_backend.get().startswith("VoxCPM2"):
            return "voxcpm2"
        if tts_backend.get().startswith("sanoTTS"):
            return "sanotts"
        if tts_backend.get().startswith("CosyVoice 3"):
            return "cosyvoice3"
        return "edge"

    def set_tts_backend(value):
        label = tts_labels.get(value)
        if label is not None:
            tts_backend.set(label)

    def selected_vad_profile():
        return vad_profile_labels[vad_profile.get()]

    def current_preferences():
        # 删除能力有意不进入此字典：每次打开面板都按本机日常约定重新设置。
        return {
            "voice": voice.get(),
            "voice_mode": selected_voice_mode(),
            "voice_latency_mode": selected_voice_latency_mode(),
            "start_page": start_page_labels[start_page.get()],
            "database": database.get().strip(),
            "voice_root": server.get().strip(),
            "lan_ip": ip.get().strip(),
            "role": selected_role(),
            "memory_extraction": selected_extraction(),
            "memory_retrieval": selected_retrieval(),
            "memory_consolidation": memory_consolidation.get(),
            "l1_sufficiency_shadow": l1_sufficiency_shadow.get(),
            "l2_sufficiency_shadow": l2_sufficiency_shadow.get(),
            "embedding_model_dir": embedding_model.get().strip(),
            "tts_backend": selected_tts(),
            "sanotts_source_root": sanotts_source.get().strip(),
            "vad_profile": selected_vad_profile(),
            "http_risk_ack": consent.get(),
        }

    _page_heading(
        daily,
        "开始今天的陪伴",
        "这里只保留每次最常用的选择和运行状态；模型、记忆、声音与维护分别放在后续页签。",
    )
    _page_heading(
        intelligence,
        "模型与记忆",
        "设置网页和圆屏使用的模型、记忆写入与召回方式。有限选择会立即保存，但运行中的服务不会热切换。",
    )
    _page_heading(
        device,
        "圆屏与声音",
        "选择现有链路或豆包实时语音备用模式。选择会保存，切换需停止后重新启动。",
    )
    _page_heading(
        maintenance,
        "本机维护",
        "路径、局域网地址和防火墙只在环境变化或排障时使用，日常启动通常无需进入本页。",
    )

    def apply_daily_recommendation():
        """恢复已验收的日用组合；不改变角色、路径、IP 或风险确认。"""
        recommended = daily_recommendation()
        voice_mode.set(next(label for label, value in voice_mode_labels.items()
                            if value == recommended["voice_mode"]))
        model_profile.set(next(
            label for label, value in model_profile_labels.items()
            if value == recommended["model_profile"]
        ))
        voice_model_profile.set(next(
            label for label, value in model_profile_labels.items()
            if value == recommended["voice_model_profile"]
        ))
        set_memory_backend(recommended["memory_backend"])
        memory_extraction.set(extraction_labels[recommended["memory_extraction"]])
        memory_retrieval.set(retrieval_labels[recommended["memory_retrieval"]])
        set_tts_backend(recommended["tts_backend"])
        vad_profile.set(next(
            label for label, value in vad_profile_labels.items()
            if value == recommended["vad_profile"]
        ))
        memory_consolidation.set(recommended["memory_consolidation"])
        l1_sufficiency_shadow.set(recommended["l1_sufficiency_shadow"])
        l2_sufficiency_shadow.set(recommended["l2_sufficiency_shadow"])
        embedding_model.set(str(DEFAULT_BGE_MODEL))
        try:
            save_preferences(choice_path, current_preferences())
        except (OSError, ValueError):
            settings_status.set("日常推荐已显示，但未能保存；请检查 data/control 是否可写。")
            return
        settings_status.set("已应用并保存日常推荐；实验开关已关闭，下次启动生效。")

    quick_box = ttk.LabelFrame(daily, text="快捷方案", style="Section.TLabelframe")
    quick_box.pack(fill="x", pady=(0, 12))
    quick_copy = ttk.Frame(quick_box, style="Card.TFrame")
    quick_copy.pack(side="left", fill="x", expand=True)
    ttk.Label(
        quick_copy,
        text="日常推荐：学校模型 · 模型辅助提取 · 混合召回 · LongMemory · CosyVoice 3",
        style="CardSelection.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        quick_copy,
        text="会关闭低频整理和两项旁路质检；不改变角色、数据库、IP 或 HTTP 风险确认。",
        style="CardHint.TLabel",
    ).pack(anchor="w", pady=(3, 0))
    ttk.Button(
        quick_box,
        text="应用日常推荐",
        command=apply_daily_recommendation,
        style="Secondary.TButton",
    ).pack(side="right", padx=(16, 0))

    mode_box = ttk.LabelFrame(daily, text="今天怎么使用", style="Section.TLabelframe")
    mode_box.pack(fill="x", pady=(0, 12))
    mode_selection = tk.StringVar()
    ttk.Label(mode_box, textvariable=mode_selection, style="Selection.TLabel").pack(
        anchor="w", pady=(0, 7)
    )
    ttk.Radiobutton(mode_box, text="文字聊天", variable=voice, value=False).pack(anchor="w", pady=(2, 1))
    ttk.Label(mode_box, text="只启动网页控制台，不启动小智语音服务。", style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 8))
    ttk.Radiobutton(mode_box, text="文字聊天＋圆屏语音", variable=voice, value=True).pack(anchor="w", pady=(1, 1))
    ttk.Label(mode_box, text="同时启动小智；启动前自动核对并备份同步网络、声音、模型和记忆后端。", style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 2))
    open_row = ttk.Frame(mode_box)
    open_row.pack(fill="x", pady=(12, 2))
    ttk.Label(open_row, text="启动后打开：").pack(side="left")
    ttk.Combobox(open_row, textvariable=start_page, values=tuple(start_page_labels), state="readonly", width=16).pack(side="left")

    paths_box = ttk.LabelFrame(maintenance, text="本机路径", style="Section.TLabelframe")
    paths_box.pack(fill="x", pady=(0, 10))
    for label, variable in [("日常数据库（已有文件）", database), ("小智目录（仅语音模式）", server)]:
        ttk.Label(paths_box, text=label).pack(anchor="w", pady=(5, 0))
        ttk.Entry(paths_box, textvariable=variable).pack(fill="x")
    network_box = ttk.LabelFrame(maintenance, text="圆屏网络", style="Section.TLabelframe")
    network_box.pack(fill="x", pady=10)
    ttk.Label(network_box, text='电脑局域网 IP（多网卡时请选择圆屏能访问的地址）').pack(anchor='w')
    address_row = ttk.Frame(network_box)
    address_row.pack(fill='x')
    addresses = ttk.Combobox(address_row, textvariable=ip, state='readonly', width=23)
    addresses.pack(side='left')
    network_status = tk.StringVar()

    def refresh():
        try:
            values = local_addresses()
            previous = ip.get()
            addresses.config(values=values)
            if previous not in values:
                ip.set(values[0] if len(values) == 1 else '')
            network_status.set(f'上次地址 {previous} 已失效；请选择并同步配置。' if previous and previous not in values
                               else '已刷新；同步后还需检查圆屏 OTA 地址和防火墙。')
        except (ValueError, OSError):
            network_status.set('无法读取本机网卡，请连接网络后刷新。')

    def sync_address():
        if manager.services:
            messagebox.showinfo('请先停止', '请先停止本面板服务；也请结束外部终端中的小智服务。')
            return
        try:
            selected = ip.get().strip()
            info = config_action(Path(server.get()), selected)
            if messagebox.askyesno('同步小智网络配置？',
                    f"配置地址 {info['old_ip']} → {selected}\n仅修改监听、WebSocket、视觉接口地址，原目录备份。\n请确认外部小智服务已停止。不会修改防火墙或圆屏。"):
                config_action(Path(server.get()), selected, apply=True)
                save_preferences(choice_path, current_preferences())
                network_status.set(f'已同步。圆屏 OTA：http://{selected}:8003/xiaozhi/ota/；防火墙见指南。')
        except (ValueError, OSError) as error:
            messagebox.showerror('未完成同步', str(error))

    ttk.Button(address_row, text='刷新地址', command=refresh).pack(side='left', padx=8)
    ttk.Button(address_row, text='同步小智地址', command=sync_address).pack(side='left')
    ttk.Button(address_row, text='网络与防火墙', command=lambda: open_panel(window, ip.get(), ROOT)).pack(side='left', padx=8)
    ttk.Label(network_box, textvariable=network_status, wraplength=760).pack(anchor='w', pady=(8, 0))
    refresh()
    behavior_box = ttk.LabelFrame(intelligence, text="日常智能", style="Section.TLabelframe")
    behavior_box.pack(fill="x", pady=10)
    row = ttk.Frame(behavior_box)
    row.pack(fill="x", pady=8)
    ttk.Label(row, text="网页角色：").pack(side="left")
    ttk.Combobox(row, textvariable=role, values=tuple(role_labels),
                 state="readonly", width=18).pack(side="left")
    ttk.Label(row, text="  只影响网页回答；圆屏角色需在设置中心明确同步").pack(side="left")
    model_row = ttk.Frame(behavior_box)
    model_row.pack(fill="x", pady=8)
    ttk.Label(model_row, text="网页与记忆模型：").pack(side="left")
    ttk.Combobox(model_row, textvariable=model_profile, values=tuple(model_profile_labels),
                 state="readonly", width=31).pack(side="left")
    ttk.Label(model_row, text="  用于网页聊天、提取与低频整理").pack(side="left")
    voice_model_row = ttk.Frame(behavior_box)
    voice_model_row.pack(fill="x", pady=8)
    ttk.Label(voice_model_row, text="现有链路模型：").pack(side="left")
    voice_model_selector = ttk.Combobox(voice_model_row, textvariable=voice_model_profile,
                                        values=tuple(model_profile_labels), state="readonly", width=31)
    voice_model_selector.pack(side="left")
    ttk.Label(voice_model_row, text="  启动语音前自动备份并同步小智配置").pack(side="left")
    backend_row = ttk.Frame(behavior_box)
    backend_row.pack(fill="x", pady=8)
    ttk.Label(backend_row, text="现有链路记忆：").pack(side="left")
    memory_backend_selector = ttk.Combobox(backend_row, textvariable=memory_backend,
                                           values=tuple(memory_backend_labels), state="readonly", width=31)
    memory_backend_selector.pack(side="left")
    ttk.Label(backend_row, text="  下次启动生效；各后端数据隔离").pack(side="left")
    memory_row = ttk.Frame(behavior_box)
    memory_row.pack(fill="x", pady=8)
    ttk.Label(memory_row, text="长期记忆提取：").pack(side="left")
    ttk.Combobox(memory_row, textvariable=memory_extraction,
                 values=("规则提取（基础/对照）", "模型辅助提取（日常推荐）"),
                 state="readonly", width=36).pack(side="left")
    ttk.Label(memory_row, text="  模型失败仍保留 L0，不静默回退").pack(side="left")
    retrieval_row = ttk.Frame(behavior_box)
    retrieval_row.pack(fill="x", pady=8)
    ttk.Label(retrieval_row, text="长期记忆召回：").pack(side="left")
    ttk.Combobox(retrieval_row, textvariable=memory_retrieval,
                 values=("关键词召回（基础/对照）", "关键词＋BGE 混合召回（日常推荐）"),
                 state="readonly", width=36).pack(side="left")
    _boolean_option(
        behavior_box,
        allow_memory_delete,
        title="L1 单条删除权限",
        description="网页仍需逐条确认；会保留 L0 原话、备份和日志。本机日常每次打开面板默认允许。",
        enabled_text="已允许",
        disabled_text="未允许",
    )
    experiment_box = ttk.LabelFrame(
        intelligence, text="实验与质检开关", style="Section.TLabelframe"
    )
    experiment_box.pack(fill="x", pady=10)
    ttk.Label(
        experiment_box,
        text="通常保持关闭。开启会增加模型请求或后台工作，但不会自动提高正式回答质量。",
        style="WarningHint.TLabel",
        wraplength=760,
    ).pack(anchor="w", pady=(0, 9))
    _boolean_option(
        experiment_box,
        memory_consolidation,
        title="低频自动整理",
        description="后台按预算和风险规则尝试 L1 → L2 → L3；个人日用默认关闭。",
    )
    _boolean_option(
        experiment_box,
        l1_sufficiency_shadow,
        title="L1 证据旁路质检",
        description="增加模型请求并记录证据充分性判断；不改变正式召回或回答，默认关闭。",
    )
    _boolean_option(
        experiment_box,
        l2_sufficiency_shadow,
        title="L2 证据旁路质检",
        description="增加模型请求并记录场景证据判断；不改变正式召回或回答，默认关闭。",
    )
    model_resource_box = ttk.LabelFrame(
        maintenance, text="模型资源（仅排障）", style="Section.TLabelframe"
    )
    model_resource_box.pack(fill="x", pady=10)
    ttk.Label(model_resource_box, text="BGE 本地快照（仅混合召回使用）").pack(
        anchor="w", pady=(0, 4)
    )
    embedding_row = ttk.Frame(model_resource_box)
    embedding_row.pack(fill="x")
    ttk.Entry(embedding_row, textvariable=embedding_model).pack(side="left", fill="x", expand=True)
    ttk.Button(embedding_row, text="选择目录", command=lambda: (
        embedding_model.set(path) if (path := filedialog.askdirectory(
            parent=window, initialdir=embedding_model.get() or str(ROOT))) else None
    )).pack(side="left", padx=(8, 0))
    sound_box = ttk.LabelFrame(device, text="圆屏声音", style="Section.TLabelframe")
    sound_box.pack(fill="x", pady=10)
    voice_mode_row = ttk.Frame(sound_box)
    voice_mode_row.pack(fill="x", pady=(0, 10))
    ttk.Label(voice_mode_row, text="语音模式：").pack(side="left")
    ttk.Combobox(voice_mode_row, textvariable=voice_mode,
                 values=tuple(voice_mode_labels), state="readonly", width=28).pack(side="left")
    ttk.Button(voice_mode_row, text="配置豆包 API", command=lambda: open_doubao_configuration(
        window, ROOT / ".env.doubao.local",
        lambda: settings_status.set("豆包配置已保存到本机，尚未验证云端权限和实际通话。"),
    )).pack(side="left", padx=8)
    ttk.Button(voice_mode_row, text="配置指南", command=lambda: os.startfile(
        ROOT / "docs/guides/豆包实时语音备用模式.md"
    )).pack(side="left")
    ttk.Label(sound_box,
              text="豆包备用模式由云端负责听、回答和说话，圆屏长期记忆暂不接入；网页记忆功能保持现状。",
              wraplength=760, style="Subtitle.TLabel").pack(anchor="w", pady=(0, 10))
    tts_row = ttk.Frame(sound_box)
    tts_row.pack(fill="x")
    ttk.Label(tts_row, text="现有链路声音：").pack(side="left")
    tts_selector = ttk.Combobox(tts_row, textvariable=tts_backend,
                                values=tuple(tts_labels.values()), state="readonly", width=42)
    tts_selector.pack(side="left")

    latency_row = ttk.Frame(sound_box)
    latency_row.pack(fill="x", pady=(10, 0))
    ttk.Label(latency_row, text="响应策略：").pack(side="left")
    latency_selector = ttk.Combobox(latency_row, textvariable=voice_latency_mode,
                                   values=tuple(voice_latency_labels), state="readonly", width=28)
    latency_selector.pack(side="left")
    ttk.Button(latency_row, text="配置联网搜索", command=lambda: open_web_search_configuration(window)).pack(side="left", padx=8)
    ttk.Label(latency_row, text="  停止并重新启动后生效；只影响现有语音链路").pack(side="left")

    tts_description = tk.StringVar()
    tts_note = ttk.Frame(sound_box, padding=(12, 10), style="Option.TFrame")
    tts_note.pack(fill="x", pady=(10, 0))
    ttk.Label(tts_note, text="当前选择", style="OptionTitle.TLabel").pack(anchor="w")
    ttk.Label(
        tts_note,
        textvariable=tts_description,
        style="OptionHint.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(3, 0))

    def update_tts_description(*_):
        if selected_voice_mode() == "doubao_realtime":
            tts_description.set("已选择豆包实时语音备用模式。需先开通并配置专用凭据；不会加载本地 ASR、声音模型或访问圆屏长期记忆。下方声音与拾音选项仅在切回现有链路后生效。")
            return
        tts_description.set({
            "cosyvoice3": "日常推荐。声音质量和连续性已通过实机体验；首声速度仍在优化，需要本地模型与显卡。",
            "edge": "联网稳定回退。资源占用低，但依赖公网并按完整音频段返回。",
            "voxcpm2": "本地参考声线实验方案。可调表达，首声较慢且占用更多显存。",
            "sanotts": "实验速度基线。资源较轻、生成较快，但当前小雅音色质量不作为日常推荐。",
        }[selected_tts()])

    tts_backend.trace_add("write", update_tts_description)
    voice_mode.trace_add("write", update_tts_description)
    update_tts_description()

    settings_status = tk.StringVar(value="选择会立即保存；运行中的服务不会热切换。")

    def persist_launcher_choices(*_):
        """枚举选择即刻保存；启动失败或直接关窗也不再丢失用户意图。"""
        try:
            save_preferences(choice_path, current_preferences())
            settings_status.set("当前选择已保存；运行中的服务不热切换，下次启动生效。")
        except (OSError, ValueError):
            settings_status.set("当前选择未能保存；请勿关闭面板，并检查 data/control 是否可写。")

    def persist_model_profile(target):
        try:
            value = (selected_model_profile() if target == "web"
                     else selected_voice_model_profile())
            save_model_profile(model_profile_path, value, target)
            settings_status.set("模型选择已保存；运行中的服务不热切换，下次启动生效。")
        except (OSError, ValueError):
            settings_status.set("模型选择未能保存；请勿关闭面板，并检查 data/control 是否可写。")

    def persist_memory_backend(*_):
        try:
            save_memory_backend(memory_backend_path, selected_memory_backend())
            settings_status.set("圆屏记忆后端已保存；下次启动生效。")
        except (OSError, ValueError):
            settings_status.set("圆屏记忆后端未能保存；请检查 data/control 是否可写。")

    def persist_tts_backend(*_):
        try:
            save_tts_backend(tts_backend_path, selected_tts())
            # launcher.json 中仍保留兼容副本；共享指针是下次启动的权威值。
            save_preferences(choice_path, current_preferences())
            settings_status.set("圆屏声音已保存；运行中的声音不热切换，下次启动生效。")
        except (OSError, ValueError):
            settings_status.set("圆屏声音未能保存；请检查 data/control 是否可写。")

    # 路径输入仍在启动或显式同步时保存，避免每次键入都写磁盘；下面这些
    # 有限枚举和布尔选择则在用户操作时立即落盘。
    for variable in (
        voice, voice_mode, voice_latency_mode, start_page, role, memory_extraction, memory_retrieval,
        memory_consolidation, l1_sufficiency_shadow, l2_sufficiency_shadow,
        vad_profile, consent,
    ):
        variable.trace_add("write", persist_launcher_choices)
    model_profile.trace_add("write", lambda *_: persist_model_profile("web"))
    voice_model_profile.trace_add("write", lambda *_: persist_model_profile("voice"))
    memory_backend.trace_add("write", persist_memory_backend)
    tts_backend.trace_add("write", persist_tts_backend)

    def sync_tts():
        if selected_voice_mode() == "doubao_realtime":
            messagebox.showinfo("豆包实时语音", "当前选择豆包模式，无需同步本地声音配置。")
            return
        if manager.services:
            messagebox.showinfo("请先停止", "请先停止本面板服务；也请结束外部终端中的小智服务。")
            return
        try:
            backend = selected_tts()
            checked = tts_config_action(Path(server.get()), ROOT, backend)
            if checked["config_matches"]:
                settings_status.set("小智声音配置已经匹配；运行中是否生效仍需重启验证。")
                return
            label = {
                "edge": "EdgeTTS",
                "voxcpm2": "VoxCPM2 本地声音",
                "sanotts": "sanoTTS 本地中文小雅",
                "cosyvoice3": "CosyVoice 3 本地高质量声音",
            }[backend]
            if messagebox.askyesno("同步圆屏声音？",
                    f"将小智 TTS 切换为 {label}。\n只修改 TTS 选择与固定接口字段，原配置会备份；不会启动服务。"):
                tts_config_action(Path(server.get()), ROOT, backend, apply=True,
                                  expected_digest=checked["digest"])
                settings_status.set("声音配置已同步；下次启动小智加载，实机效果仍需试听。")
        except (ValueError, OSError, KeyError):
            messagebox.showerror("未完成同步", "TTS 配置检查或同步失败；未显示私有配置内容。")

    ttk.Button(tts_row, text="检查并同步", command=sync_tts).pack(side="left", padx=8)
    sano_resource_box = ttk.LabelFrame(
        maintenance, text="实验声音资源（仅排障）", style="Section.TLabelframe"
    )
    sano_resource_box.pack(fill="x", pady=10)
    sano_row = ttk.Frame(sano_resource_box)
    sano_row.pack(fill="x")
    ttk.Label(sano_row, text="sanoTTS 外部目录：").pack(side="left")
    ttk.Entry(sano_row, textvariable=sanotts_source).pack(side="left", fill="x", expand=True)
    ttk.Button(sano_row, text="选择目录", command=lambda: (
        sanotts_source.set(path) if (path := filedialog.askdirectory(
            parent=window, initialdir=sanotts_source.get() or str(DEFAULT_SANOTTS_SOURCE))) else None
    )).pack(side="left", padx=(8, 0))
    vad_row = ttk.Frame(sound_box)
    vad_row.pack(fill="x", pady=(10, 0))
    ttk.Label(vad_row, text="拾音环境：").pack(side="left")
    vad_selector = ttk.Combobox(vad_row, textvariable=vad_profile,
                                values=tuple(vad_profile_labels), state="readonly", width=31)
    vad_selector.pack(side="left")
    ttk.Label(vad_row, text="  下次统一启动前自动备份并同步").pack(side="left")

    def update_voice_controls(*_):
        selector_state = "readonly" if selected_voice_mode() == "pipeline" else "disabled"
        for selector in (voice_model_selector, memory_backend_selector, tts_selector, vad_selector, latency_selector):
            selector.configure(state=selector_state)

    voice_mode.trace_add("write", update_voice_controls)
    update_voice_controls()
    save_bar = ttk.Frame(footer, padding=(12, 8), style="Save.TFrame")
    save_bar.pack(fill="x", pady=(0, 9))
    save_marker = ttk.Label(save_bar, text="●  本机保存", style="Save.TLabel")
    save_marker.pack(side="left")
    save_message = ttk.Label(
        save_bar,
        textvariable=settings_status,
        style="Save.TLabel",
        wraplength=760,
    )
    save_message.pack(side="left", padx=(10, 0), fill="x", expand=True)

    def render_save_status(*_):
        style_name = (
            "SaveError.TLabel"
            if any(word in settings_status.get() for word in ("未能", "失败"))
            else "Save.TLabel"
        )
        save_marker.configure(style=style_name)
        save_message.configure(style=style_name)

    settings_status.trace_add("write", render_save_status)
    render_save_status()

    summary = tk.StringVar()

    def update_summary(*_):
        experimental_count = sum((
            bool(memory_consolidation.get()),
            bool(l1_sufficiency_shadow.get()),
            bool(l2_sufficiency_shadow.get()),
        ))
        tabs.tab(
            intelligence_tab,
            text=(f"模型与记忆 · 实验 {experimental_count}"
                  if experimental_count else "模型与记忆"),
        )
        mode_selection.set(
            "当前选择：文字聊天＋圆屏语音" if voice.get()
            else "当前选择：文字聊天"
        )
        summary.set(_summary_text(
            voice.get(), start_page_labels[start_page.get()], selected_role(), selected_extraction(), selected_retrieval(),
            selected_tts(), allow_memory_delete.get(), memory_consolidation.get(),
            selected_memory_backend(),
            selected_vad_profile(),
            l2_sufficiency_shadow.get(),
            l1_sufficiency_shadow.get(),
            model_profile=selected_model_profile(),
            voice_model_profile=selected_voice_model_profile(),
            voice_mode=selected_voice_mode(),
        ))

    summary_box = ttk.LabelFrame(daily, text="本次配置", style="Section.TLabelframe")
    summary_box.pack(fill="x", pady=12)
    ttk.Label(summary_box, textvariable=summary, wraplength=760, style="Summary.TLabel").pack(anchor="w")
    ttk.Label(
        summary_box,
        text="详细路径和算法选项在“高级设置”；有限选项选择后立即保存，路径在成功启动后保存。",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(4, 0))
    for variable in (voice, voice_mode, start_page, role, model_profile, voice_model_profile,
                     memory_extraction, memory_retrieval, tts_backend, vad_profile,
                     memory_backend, allow_memory_delete,
                     memory_consolidation, l1_sufficiency_shadow,
                     l2_sufficiency_shadow):
        variable.trace_add("write", update_summary)
    update_summary()

    if saved["http_risk_ack"]:
        ttk.Label(
            daily,
            text="✓ 已记住：校园模型使用 HTTP，凭据与内容会明文传输。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=8)
    else:
        _boolean_option(
            daily,
            consent,
            title="校园模型 HTTP 风险确认",
            description="凭据与对话内容会明文传输；确认后记住选择，不再每次询问。",
            enabled_text="已了解",
            disabled_text="待确认",
        )
    status = tk.StringVar(value="尚未启动。学校模型是否可用需你在校园网自行验证。")
    status_box = ttk.LabelFrame(daily, text="运行状态", style="Section.TLabelframe")
    status_box.pack(fill="x", pady=12)
    status_row = ttk.Frame(status_box)
    status_row.pack(fill="x")
    status_indicator = ttk.Label(status_row, text="●", style="StatusIdle.TLabel")
    status_indicator.pack(side="left", anchor="n", padx=(0, 9))
    ttk.Label(status_row, textvariable=status, wraplength=720).pack(side="left", fill="x", expand=True)

    # 启动器只能证明自己拥有的进程和本机网页状态，不能证明圆屏已经连入。
    # 四项短状态便于扫读，下面的完整文字继续解释错误边界和下一步。
    component_values = {
        "console": tk.StringVar(value="已停止"),
        "voice": tk.StringVar(value="未启动"),
        "speech": tk.StringVar(value="未启动"),
        "browser": tk.StringVar(value="未打开"),
    }
    component_dots = {}
    service_grid = ttk.Frame(status_box)
    service_grid.pack(fill="x", pady=(14, 0))
    for index, (key, title) in enumerate((
        ("console", "网页控制台"), ("voice", "小智语音"),
        ("speech", "声音服务"), ("browser", "网页入口"),
    )):
        cell = ttk.Frame(service_grid, padding=(12, 9), style="StatusCell.TFrame")
        cell.pack(side="left", fill="x", expand=True,
                  padx=(0 if index == 0 else 4, 0 if index == 3 else 4))
        heading = ttk.Frame(cell, style="StatusCell.TFrame")
        heading.pack(fill="x")
        dot = ttk.Label(heading, text="●", style="StatusCellIdle.TLabel")
        dot.pack(side="left", padx=(0, 6))
        ttk.Label(heading, text=title, style="StatusCellTitle.TLabel").pack(side="left")
        ttk.Label(cell, textvariable=component_values[key],
                  style="StatusCellValue.TLabel").pack(anchor="w", pady=(4, 0))
        component_dots[key] = dot

    def set_status(message, tone="idle"):
        """状态颜色只帮助扫读；完整文字仍是故障判断的唯一依据。"""
        styles = {"idle": "StatusIdle.TLabel", "busy": "StatusBusy.TLabel",
                  "good": "StatusGood.TLabel", "error": "StatusError.TLabel"}
        status.set(message)
        status_indicator.configure(style=styles.get(tone, "StatusIdle.TLabel"))

    def set_component(key, message, tone="idle"):
        styles = {"idle": "StatusCellIdle.TLabel", "busy": "StatusCellBusy.TLabel",
                  "good": "StatusCellGood.TLabel", "error": "StatusCellError.TLabel"}
        component_values[key].set(message)
        component_dots[key].configure(style=styles.get(tone, "StatusCellIdle.TLabel"))

    def apply_presentation(presentation):
        """Tk 只应用纯视图模型，不再自行推导各组件文案。"""
        for key, (message, tone) in presentation["components"].items():
            set_component(key, message, tone)
        set_status(presentation["message"], presentation["tone"])
    buttons = ttk.Frame(footer, style="Footer.TFrame")
    buttons.pack(fill="x")
    state = {"opened": False, "started": 0.0, "failed": False}

    def open_page():
        if manager.ready():
            webbrowser.open(console_url(manager.options.port, start_page_labels[start_page.get()]))
            set_component("browser", "已请求打开", "good")
        else:
            messagebox.showinfo("尚未就绪", "请先启动并等待控制台就绪。")

    def stop(confirm=True):
        if manager.services and confirm and not messagebox.askyesno("停止本面板启动的服务？",
                "请先结束聊天。停止会中断当前回答/语音，未完成操作可能已写入；不会删除数据库。"):
            return False
        # 网页可在服务运行时保存“下次启动”项。只有面板下拉框仍等于本次
        # 运行值时才吸收网页选择；若用户已在面板手动改过，则保留面板意图。
        running_backend = (manager.options.memory_backend
                           if manager.options is not None
                           and manager.options.voice_mode == "pipeline" else None)
        panel_unchanged = (running_backend is not None
                           and selected_memory_backend() == running_backend)
        running_tts = (manager.options.tts_backend if manager.options is not None
                       and manager.options.voice_mode == "pipeline" else None)
        tts_panel_unchanged = running_tts is not None and selected_tts() == running_tts
        try:
            manager.stop()
        except Exception:
            set_status("停止未完全确认，请关闭面板并检查服务，不要重复启动。", "error")
            return False
        state.update(opened=False, failed=False)
        if panel_unchanged:
            next_memory_backend = load_memory_backend(memory_backend_path)
            set_memory_backend(next_memory_backend)
            memory_backend_pointer_seen["backend"] = next_memory_backend
        if tts_panel_unchanged:
            next_tts = load_tts_backend(tts_backend_path, running_tts)
            set_tts_backend(next_tts)
            tts_pointer_seen["backend"] = next_tts
        start_button.config(state="normal")
        apply_presentation(stopped_services())
        return True

    def close_external_voice():
        """安全清理遗留小智，以及当前所选且身份匹配的本地 TTS。"""
        if manager.services:
            set_status("本面板当前拥有受管服务；请使用“停止服务”结束整棵进程树。", "busy")
            return
        try:
            voice_result = close_stale_voice(ip.get().strip())
            tts_result = (close_stale_tts(selected_tts()) if selected_voice_mode() == "pipeline"
                          else {"state": "free"})
        except ValueError as error:
            set_status(str(error), "error")
            return
        stopped = []
        refused = []
        if voice_result["state"] == "stopped":
            set_component("voice", "遗留进程已停止", "good")
            stopped.append(f"小智 PID {voice_result['process_id']}")
        elif voice_result["state"] != "free":
            refused.append("小智三端口身份不匹配")
        if tts_result["state"] == "stopped":
            set_component("speech", "遗留进程已停止", "good")
            stopped.append(f"{tts_result['provider']} PID {tts_result['process_id']}")
        elif tts_result["state"] != "free":
            refused.append(f"{tts_result['provider']} 端口身份不匹配")
        if refused:
            prefix = ("已停止 " + "、".join(stopped) + "；") if stopped else ""
            set_status(prefix + "已拒绝处理 " + "、".join(refused) + "，请人工核对。", "error")
        elif stopped:
            set_status("已安全停止 " + "、".join(stopped) + "；未批量结束其他 Python/Node。", "good")
        else:
            message = ("小智无遗留监听，无需清理。" if selected_voice_mode() == "doubao_realtime"
                       else "小智和当前所选声音后端均无遗留监听，无需清理。")
            set_status(message, "good")

    def start(show_dialog=True):
        try:
            # 网页设置也能修改下次启动指针。若面板自打开后没有亲自改过
            # 对应下拉框，启动瞬间吸收外部新值；否则保留面板上的用户选择。
            if selected_model_profile() == model_pointer_seen["web"]:
                next_model = load_model_profile(model_profile_path, "web")
                model_profile.set(next(
                    label for label, value in model_profile_labels.items()
                    if value == next_model
                ))
                model_pointer_seen["web"] = next_model
            if (selected_voice_mode() == "pipeline"
                    and selected_voice_model_profile() == model_pointer_seen["voice"]):
                next_voice_model = load_model_profile(model_profile_path, "voice")
                voice_model_profile.set(next(
                    label for label, value in model_profile_labels.items()
                    if value == next_voice_model
                ))
                model_pointer_seen["voice"] = next_voice_model
            if (selected_voice_mode() == "pipeline"
                    and selected_memory_backend() == memory_backend_pointer_seen["backend"]):
                next_memory_backend = load_memory_backend(memory_backend_path)
                set_memory_backend(next_memory_backend)
                memory_backend_pointer_seen["backend"] = next_memory_backend
            if (selected_voice_mode() == "pipeline"
                    and selected_tts() == tts_pointer_seen["backend"]):
                next_tts = load_tts_backend(tts_backend_path, selected_tts())
                set_tts_backend(next_tts)
                tts_pointer_seen["backend"] = next_tts
            options = Options(database=Path(database.get()), voice=voice.get(), voice_root=Path(server.get()),
                              voice_mode=selected_voice_mode(),
                              voice_latency_mode=selected_voice_latency_mode(),
                              lan_ip=ip.get().strip(), role=selected_role(), consent=consent.get(),
                              tts_backend=selected_tts(),
                              sanotts_source_root=Path(sanotts_source.get()),
                              vad_profile=selected_vad_profile(),
                              memory_extraction=selected_extraction(),
                              memory_retrieval=selected_retrieval(),
                              enable_memory_consolidation=memory_consolidation.get(),
                              enable_l1_sufficiency_shadow=l1_sufficiency_shadow.get(),
                              enable_l2_sufficiency_shadow=l2_sufficiency_shadow.get(),
                              allow_memory_delete=allow_memory_delete.get(),
                              embedding_model_dir=Path(embedding_model.get()),
                              model_profile=selected_model_profile(),
                              voice_model_profile=selected_voice_model_profile(),
                              memory_backend=selected_memory_backend())
            manager.start(options)
            try:
                save_preferences(choice_path, current_preferences())
                save_model_profile(model_profile_path, selected_model_profile())
                if selected_voice_mode() == "pipeline":
                    save_model_profile(model_profile_path, selected_voice_model_profile(), "voice")
                    save_memory_backend(memory_backend_path, selected_memory_backend())
                    save_tts_backend(tts_backend_path, selected_tts())
                model_pointer_seen["web"] = selected_model_profile()
                model_pointer_seen["voice"] = selected_voice_model_profile()
                memory_backend_pointer_seen["backend"] = selected_memory_backend()
                tts_pointer_seen["backend"] = selected_tts()
            except OSError:
                settings_status.set("服务已启动，但本机首选项未保存；下次仍可手动选择。")
            state.update(started=time.monotonic(), opened=False, failed=False)
            start_button.config(state="disabled")
            apply_presentation(starting_services(
                voice=voice.get(),
                voice_mode=selected_voice_mode(),
                tts_backend=selected_tts(),
                model_profile=selected_model_profile(),
                voice_model_profile=selected_voice_model_profile(),
                memory_backend=selected_memory_backend(),
            ))
            return True
        except ValueError as error:
            if show_dialog:
                messagebox.showerror("无法启动", str(error))
            else:
                set_status(str(error), "error")
        except Exception:
            message = "无法建立受管进程。未关闭外部程序；请查看启动指南。"
            if show_dialog:
                messagebox.showerror("无法启动", message)
            else:
                set_status(message, "error")
        return False

    def dispatch_control(action):
        """本机接口复用面板当前选择；不开放配置、清理或窗口关闭。"""
        if action == "status":
            return {
                "ok": True,
                "state": "running" if manager.services else "stopped",
                "ready": bool(manager.services and manager.ready()),
                "selection": {
                    "voice": bool(voice.get()),
                    "voice_mode": selected_voice_mode(),
                    "start_page": start_page_labels[start_page.get()],
                    "model_profile": selected_model_profile(),
                    "voice_model_profile": selected_voice_model_profile(),
                    "memory_backend": selected_memory_backend(),
                    "memory_extraction": selected_extraction(),
                    "memory_retrieval": selected_retrieval(),
                    "tts_backend": selected_tts(),
                    "vad_profile": selected_vad_profile(),
                    "memory_consolidation": bool(memory_consolidation.get()),
                    "l1_sufficiency_shadow": bool(l1_sufficiency_shadow.get()),
                    "l2_sufficiency_shadow": bool(l2_sufficiency_shadow.get()),
                },
            }
        if action == "start":
            if manager.services:
                return {"ok": True, "state": "already_running"}
            started = start(False)
            return {
                "ok": started,
                "state": "starting" if started else "start_failed",
            }
        if action == "stop":
            if not manager.services:
                return {"ok": True, "state": "already_stopped"}
            stopped = stop(False)
            return {"ok": stopped, "state": "stopped" if stopped else "stop_failed"}
        return {"ok": False, "error": "action_not_allowed"}

    def tick():
        control.poll(dispatch_control)
        if manager.services and not state["failed"]:
            exited = [(name, service.process.poll()) for name, service in manager.services.items()
                      if service.process.poll() is not None]
            if exited:
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    apply_presentation(failed_services(
                        exited,
                        manager.options.tts_backend if manager.options else None,
                        manager.options.voice_mode if manager.options else "pipeline",
                    ))
            elif manager.ready():
                if not state["opened"]:
                    state["opened"] = True
                    open_page()
                local_tts_ready = (manager.local_tts_ready()
                                   if manager.options.voice
                                   and manager.options.voice_mode == "pipeline"
                                   and manager.options.tts_backend in {"voxcpm2", "sanotts", "cosyvoice3"}
                                   else False)
                apply_presentation(ready_services(
                    voice=manager.options.voice,
                    voice_mode=manager.options.voice_mode,
                    tts_backend=manager.options.tts_backend,
                    local_tts_ready=local_tts_ready,
                    opened=state["opened"],
                ))
                manager.publish_status(
                    "ready",
                    console_ready=True,
                    voice_ready=manager.options.voice,
                    tts_ready=local_tts_ready,
                )
            elif time.monotonic() - state["started"] > 90:
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    apply_presentation(readiness_timeout())
            else:
                manager.publish_status("starting")
        window.after(1000, tick)

    def close():
        if stop():
            lock.close()
            window.destroy()

    start_button = ttk.Button(buttons, text="启动服务并打开网页", command=start, style="Primary.TButton")
    start_button.pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="重新打开网页", command=open_page, style="Secondary.TButton").pack(side="left", padx=8)
    ttk.Button(buttons, text="停止服务", command=lambda: stop(False), style="Secondary.TButton").pack(side="left", padx=8)
    ttk.Button(buttons, text="清理遗留服务", command=close_external_voice, style="Secondary.TButton").pack(side="left", padx=8)
    ttk.Button(buttons, text="使用指南", command=lambda: os.startfile(ROOT / "docs/guides/统一启动.md"), style="Secondary.TButton").pack(side="right", padx=(8, 0))
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(500, tick)
    try:
        window.mainloop()
    finally:
        try:
            manager.stop()
        finally:
            control.close()
            lock.close()


if __name__ == "__main__":
    main()

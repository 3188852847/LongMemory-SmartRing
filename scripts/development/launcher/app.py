"""无新增依赖的 Windows 日常启动面板；服务生命周期属于这个窗口。"""

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from pathlib import Path

from runtime import DEFAULT_BGE_MODEL, Manager, Options, ROOT, Singleton, VOICE_ROOT, console_url
from network import local_addresses, config_action
from preferences import (
    DEFAULT_SESSION_ALLOW_MEMORY_DELETE,
    load_memory_backend,
    load_model_profile,
    load_preferences,
    save_memory_backend,
    save_model_profile,
    save_preferences,
)
from firewall_panel import open_panel
from tts import config_action as tts_config_action
from voice_recovery import close_stale_voice


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


def _summary_text(voice, start_page, role, extraction, retrieval, tts, allow_delete,
                  consolidation, memory_backend="longmemory"):
    """把内部启动枚举翻译为日常首页可理解的三行摘要。"""
    mode = "网页＋圆屏语音" if voice else "网页文字聊天"
    page_label = {"overview": "系统总览", "chat": "聊天", "device": "设备状态", "memories": "记忆管理", "settings": "设置中心"}[start_page]
    role_label = "爱莉希雅风格" if role == "elysia_v1" else "普通助手"
    extraction_label = "模型辅助提取" if extraction == "llm" else "规则提取"
    retrieval_label = "关键词＋语义召回" if retrieval == "hybrid" else "关键词召回"
    sound_label = "VoxCPM2 本地声音" if tts == "voxcpm2" else "EdgeTTS 联网声音"
    delete_label = "允许单条删除" if allow_delete else "不开放删除"
    consolidation_label = "低频整理已开启" if consolidation else "低频整理关闭"
    backend_label = {
        "longmemory": "圆屏：LongMemory",
        "xiaozhi_local": "圆屏：小智本地摘要",
        "none": "圆屏：无长期记忆",
    }[memory_backend]
    return (
        f"{mode}  ·  打开{page_label}  ·  {role_label}\n"
        f"{extraction_label}  ·  {retrieval_label}  ·  {sound_label}\n"
        f"{delete_label}  ·  {consolidation_label}  ·  {backend_label}"
    )


def _failure_hint(exited):
    """把受管进程退出码翻译成不含原始输出的本机排障提示。

    启动面板有意不复制子进程 stdout/stderr，因为上游语音日志可能包含识别
    文本。这里仅使用组件名和稳定退出码，既能给出下一步，也不会把日志或
    私有配置带进新的持久文件。
    """
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
        elif name == "voice":
            hint = "圆屏语音进程意外退出；先核对小智配置、网络地址和 8000/8003/8766 端口"
        elif name == "console":
            hint = "网页控制台意外退出；先核对数据库、模型配置和 8767 端口"
        else:
            hint = f"{name} 组件意外退出；请打开使用指南核对该组件的本机配置"
        if hint not in hints:
            hints.append(hint)
    return "；".join(hints) + "。" if hints else "请打开使用指南核对本机配置。"


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


def main():
    window = tk.Tk()
    window.title("LongMemory · 日常启动")
    window.geometry("960x760")
    window.minsize(680, 460)
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
    saved = load_preferences(choice_path)
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
    advanced_tab, advanced, advanced_canvas = _scrollable_tab(tabs)
    tabs.add(daily_tab, text="日常启动")
    tabs.add(advanced_tab, text="高级设置")
    # 高频操作固定在页签外。窗口变矮或高级设置内容较长时，用户依然可以
    # 立即启动、停止或重新打开网页，不必先滚动到页面末尾。
    footer = ttk.Frame(box, style="Footer.TFrame")
    footer.pack(fill="x", pady=(14, 0))

    def scroll_current_tab(event):
        """鼠标位于面板任意控件上时，滚动当前可见页签。"""
        canvas = daily_canvas if tabs.index("current") == 0 else advanced_canvas
        if not event.delta:
            return
        units = -int(event.delta / 120)
        canvas.yview_scroll(units if units else (-1 if event.delta > 0 else 1), "units")

    window.bind_all("<MouseWheel>", scroll_current_tab, add="+")

    voice = tk.BooleanVar(value=saved["voice"])
    start_page_labels = {"系统总览": "overview", "聊天": "chat", "设备状态": "device", "记忆管理": "memories", "设置中心": "settings"}
    start_page = tk.StringVar(value=next(label for label, value in start_page_labels.items() if value == saved["start_page"]))
    consent = tk.BooleanVar(value=saved["http_risk_ack"])
    database = tk.StringVar(value=saved["database"] or str(ROOT / "data/databases/xiaozhi-demo-v1.db"))
    server = tk.StringVar(value=saved["voice_root"] or str(VOICE_ROOT))
    ip = tk.StringVar(value=saved["lan_ip"])
    role = tk.StringVar(value=saved["role"])
    extraction_labels = {"rules": "规则提取（基础/对照）", "llm": "模型辅助提取（日常推荐）"}
    retrieval_labels = {"keyword": "关键词召回（基础/对照）", "hybrid": "关键词＋BGE 混合召回（日常推荐）"}
    tts_labels = {"edge": "EdgeTTS（联网标准音色）", "voxcpm2": "VoxCPM2（本地 plain）"}
    memory_extraction = tk.StringVar(value=extraction_labels[saved["memory_extraction"]])
    memory_retrieval = tk.StringVar(value=retrieval_labels[saved["memory_retrieval"]])
    allow_memory_delete = tk.BooleanVar(value=DEFAULT_SESSION_ALLOW_MEMORY_DELETE)
    memory_consolidation = tk.BooleanVar(value=saved["memory_consolidation"])
    embedding_model = tk.StringVar(value=saved["embedding_model_dir"] or str(DEFAULT_BGE_MODEL))
    tts_backend = tk.StringVar(value=tts_labels[saved["tts_backend"]])
    model_profile_labels = {"学校模型（校园网）": "campus", "官方 DeepSeek（公网 HTTPS）": "official"}
    active_model_profile = load_model_profile(model_profile_path, "web")
    model_profile = tk.StringVar(value=next(label for label, value in model_profile_labels.items()
                                             if value == active_model_profile))
    active_voice_model_profile = load_model_profile(model_profile_path, "voice")
    voice_model_profile = tk.StringVar(value=next(label for label, value in model_profile_labels.items()
                                                   if value == active_voice_model_profile))
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

    def selected_model_profile():
        return model_profile_labels[model_profile.get()]

    def selected_voice_model_profile():
        return model_profile_labels[voice_model_profile.get()]

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
        return "voxcpm2" if tts_backend.get().startswith("VoxCPM2") else "edge"

    def current_preferences():
        # 删除能力有意不进入此字典：每次打开面板都按本机日常约定重新设置。
        return {
            "voice": voice.get(),
            "start_page": start_page_labels[start_page.get()],
            "database": database.get().strip(),
            "voice_root": server.get().strip(),
            "lan_ip": ip.get().strip(),
            "role": role.get(),
            "memory_extraction": selected_extraction(),
            "memory_retrieval": selected_retrieval(),
            "memory_consolidation": memory_consolidation.get(),
            "embedding_model_dir": embedding_model.get().strip(),
            "tts_backend": selected_tts(),
            "http_risk_ack": consent.get(),
        }

    mode_box = ttk.LabelFrame(daily, text="今天怎么使用", style="Section.TLabelframe")
    mode_box.pack(fill="x", pady=(0, 12))
    ttk.Radiobutton(mode_box, text="文字聊天", variable=voice, value=False).pack(anchor="w", pady=(2, 1))
    ttk.Label(mode_box, text="只启动网页控制台，不启动小智语音服务。", style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 8))
    ttk.Radiobutton(mode_box, text="文字聊天＋圆屏语音", variable=voice, value=True).pack(anchor="w", pady=(1, 1))
    ttk.Label(mode_box, text="同时启动小智；启动前自动核对并备份同步网络、声音、模型和记忆后端。", style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 2))
    open_row = ttk.Frame(mode_box)
    open_row.pack(fill="x", pady=(12, 2))
    ttk.Label(open_row, text="启动后打开：").pack(side="left")
    ttk.Combobox(open_row, textvariable=start_page, values=tuple(start_page_labels), state="readonly", width=16).pack(side="left")

    paths_box = ttk.LabelFrame(advanced, text="本机路径", style="Section.TLabelframe")
    paths_box.pack(fill="x", pady=(0, 10))
    for label, variable in [("日常数据库（已有文件）", database), ("小智目录（仅语音模式）", server)]:
        ttk.Label(paths_box, text=label).pack(anchor="w", pady=(5, 0))
        ttk.Entry(paths_box, textvariable=variable).pack(fill="x")
    network_box = ttk.LabelFrame(advanced, text="圆屏网络", style="Section.TLabelframe")
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
    behavior_box = ttk.LabelFrame(advanced, text="助手与长期记忆", style="Section.TLabelframe")
    behavior_box.pack(fill="x", pady=10)
    row = ttk.Frame(behavior_box)
    row.pack(fill="x", pady=8)
    ttk.Label(row, text="网页角色：").pack(side="left")
    ttk.Combobox(row, textvariable=role, values=("elysia_v1", "plain_v1"), state="readonly", width=18).pack(side="left")
    ttk.Label(row, text="  不自动改变小智角色；控制台端口 8767").pack(side="left")
    model_row = ttk.Frame(behavior_box)
    model_row.pack(fill="x", pady=8)
    ttk.Label(model_row, text="大模型配置：").pack(side="left")
    ttk.Combobox(model_row, textvariable=model_profile, values=tuple(model_profile_labels),
                 state="readonly", width=31).pack(side="left")
    ttk.Label(model_row, text="  网页聊天、提取与整理").pack(side="left")
    voice_model_row = ttk.Frame(behavior_box)
    voice_model_row.pack(fill="x", pady=8)
    ttk.Label(voice_model_row, text="圆屏语音模型：").pack(side="left")
    ttk.Combobox(voice_model_row, textvariable=voice_model_profile,
                 values=tuple(model_profile_labels), state="readonly", width=31).pack(side="left")
    ttk.Label(voice_model_row, text="  启动语音前自动备份并同步小智配置").pack(side="left")
    backend_row = ttk.Frame(behavior_box)
    backend_row.pack(fill="x", pady=8)
    ttk.Label(backend_row, text="圆屏记忆后端：").pack(side="left")
    ttk.Combobox(backend_row, textvariable=memory_backend,
                 values=tuple(memory_backend_labels), state="readonly", width=31).pack(side="left")
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
    ttk.Checkbutton(
        behavior_box,
        text="允许 L1 单条删除（本机日常默认开启；仍保留 L0 原话）",
        variable=allow_memory_delete,
    ).pack(anchor="w", pady=(0, 4))
    ttk.Checkbutton(
        behavior_box,
        text="启用低频自动整理（L1→L2→L3；有预算与风险复核，默认关闭）",
        variable=memory_consolidation,
    ).pack(anchor="w", pady=(0, 4))
    ttk.Label(behavior_box, text="BGE 本地快照（仅混合召回使用）").pack(anchor="w", pady=(4, 0))
    embedding_row = ttk.Frame(behavior_box)
    embedding_row.pack(fill="x")
    ttk.Entry(embedding_row, textvariable=embedding_model).pack(side="left", fill="x", expand=True)
    ttk.Button(embedding_row, text="选择目录", command=lambda: (
        embedding_model.set(path) if (path := filedialog.askdirectory(
            parent=window, initialdir=embedding_model.get() or str(ROOT))) else None
    )).pack(side="left", padx=(8, 0))
    sound_box = ttk.LabelFrame(advanced, text="圆屏声音", style="Section.TLabelframe")
    sound_box.pack(fill="x", pady=10)
    tts_row = ttk.Frame(sound_box)
    tts_row.pack(fill="x")
    ttk.Label(tts_row, text="圆屏声音：").pack(side="left")
    ttk.Combobox(tts_row, textvariable=tts_backend,
                 values=("EdgeTTS（联网标准音色）", "VoxCPM2（本地 plain）"),
                 state="readonly", width=27).pack(side="left")

    settings_status = tk.StringVar(value="高级设置只在下次启动时生效。")

    def sync_tts():
        if manager.services:
            messagebox.showinfo("请先停止", "请先停止本面板服务；也请结束外部终端中的小智服务。")
            return
        try:
            backend = selected_tts()
            checked = tts_config_action(Path(server.get()), ROOT, backend)
            if checked["config_matches"]:
                settings_status.set("小智声音配置已经匹配；运行中是否生效仍需重启验证。")
                return
            label = "VoxCPM2 本地声音" if backend == "voxcpm2" else "EdgeTTS"
            if messagebox.askyesno("同步圆屏声音？",
                    f"将小智 TTS 切换为 {label}。\n只修改 TTS 选择与固定接口字段，原配置会备份；不会启动服务。"):
                tts_config_action(Path(server.get()), ROOT, backend, apply=True,
                                  expected_digest=checked["digest"])
                settings_status.set("声音配置已同步；下次启动小智加载，实机效果仍需试听。")
        except (ValueError, OSError, KeyError):
            messagebox.showerror("未完成同步", "TTS 配置检查或同步失败；未显示私有配置内容。")

    ttk.Button(tts_row, text="检查并同步", command=sync_tts).pack(side="left", padx=8)
    ttk.Label(advanced, textvariable=settings_status, style="Subtitle.TLabel").pack(anchor="w")

    summary = tk.StringVar()

    def update_summary(*_):
        summary.set(_summary_text(
            voice.get(), start_page_labels[start_page.get()], role.get(), selected_extraction(), selected_retrieval(),
            selected_tts(), allow_memory_delete.get(), memory_consolidation.get(),
            selected_memory_backend(),
        ))

    summary_box = ttk.LabelFrame(daily, text="本次配置", style="Section.TLabelframe")
    summary_box.pack(fill="x", pady=12)
    ttk.Label(summary_box, textvariable=summary, wraplength=760, style="Summary.TLabel").pack(anchor="w")
    ttk.Label(
        summary_box,
        text="详细路径和算法选项在“高级设置”；成功启动后自动记住常用选择。",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(4, 0))
    for variable in (voice, start_page, role, memory_extraction, memory_retrieval,
                     tts_backend, memory_backend, allow_memory_delete, memory_consolidation):
        variable.trace_add("write", update_summary)
    update_summary()

    if saved["http_risk_ack"]:
        ttk.Label(
            daily,
            text="✓ 已记住：校园模型使用 HTTP，凭据与内容会明文传输。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=8)
    else:
        ttk.Checkbutton(
            daily,
            variable=consent,
            text="我已了解校园模型 HTTP 明文传输风险；以后不再每次询问",
        ).pack(anchor="w", pady=8)
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
                           if manager.options is not None else None)
        panel_unchanged = (running_backend is not None
                           and selected_memory_backend() == running_backend)
        try:
            manager.stop()
        except Exception:
            set_status("停止未完全确认，请关闭面板并检查服务，不要重复启动。", "error")
            return False
        state.update(opened=False, failed=False)
        if panel_unchanged:
            set_memory_backend(load_memory_backend(memory_backend_path))
        start_button.config(state="normal")
        set_component("console", "已停止")
        set_component("voice", "未启动")
        set_component("speech", "未启动")
        set_component("browser", "未打开")
        set_status("已停止本面板启动的服务；其他终端启动的程序未被停止。")
        return True

    def close_external_voice():
        """只清理符合固定三端口契约的外部/遗留小智，不批量结束 Python。"""
        if manager.services:
            set_status("本面板当前拥有受管服务；请使用“停止服务”结束整棵进程树。", "busy")
            return
        try:
            result = close_stale_voice(ip.get().strip())
        except ValueError as error:
            set_status(str(error), "error")
            return
        if result["state"] == "free":
            set_status("所选地址的 8000 当前没有监听者，无需清理。", "good")
        elif result["state"] == "stopped":
            set_component("voice", "遗留进程已停止", "good")
            set_status(
                f"已停止经 8000/8003/8766 共同归属核验的小智语音进程（PID {result['process_id']}）；未停止控制台、VoxCPM2 或其他 Python。",
                "good",
            )
        elif result["state"] == "refused":
            set_status("8000 的监听者不符合本项目小智三端口契约，已拒绝停止；请人工核对占用程序。", "error")
        else:
            set_status("停止结果未能确认，请重新检查端口；不要连续点击。", "error")

    def start():
        try:
            options = Options(database=Path(database.get()), voice=voice.get(), voice_root=Path(server.get()),
                              lan_ip=ip.get().strip(), role=role.get(), consent=consent.get(),
                              tts_backend=selected_tts(),
                              memory_extraction=selected_extraction(),
                              memory_retrieval=selected_retrieval(),
                              enable_memory_consolidation=memory_consolidation.get(),
                              allow_memory_delete=allow_memory_delete.get(),
                              embedding_model_dir=Path(embedding_model.get()),
                              model_profile=selected_model_profile(),
                              voice_model_profile=selected_voice_model_profile(),
                              memory_backend=selected_memory_backend())
            manager.start(options)
            try:
                save_preferences(choice_path, current_preferences())
                save_model_profile(model_profile_path, selected_model_profile())
                save_model_profile(model_profile_path, selected_voice_model_profile(), "voice")
                save_memory_backend(memory_backend_path, selected_memory_backend())
            except OSError:
                settings_status.set("服务已启动，但本机首选项未保存；下次仍可手动选择。")
            state.update(started=time.monotonic(), opened=False, failed=False)
            start_button.config(state="disabled")
            set_component("console", "启动中", "busy")
            set_component("voice", "启动中" if voice.get() else "本次未启用",
                          "busy" if voice.get() else "idle")
            set_component("speech", ("VoxCPM2 加载中" if selected_tts() == "voxcpm2"
                                      else "EdgeTTS 已选择") if voice.get() else "本次未启用",
                          "busy" if voice.get() else "idle")
            set_component("browser", "等待控制台", "busy")
            model_label = "官方 DeepSeek" if selected_model_profile() == "official" else "学校模型"
            voice_model_label = "官方 DeepSeek" if selected_voice_model_profile() == "official" else "学校模型"
            memory_label = {"longmemory": "LongMemory", "xiaozhi_local": "小智本地摘要", "none": "无长期记忆"}[selected_memory_backend()]
            set_status(f"正在启动；网页使用 {model_label}" +
                       (f"，圆屏使用 {voice_model_label} / {memory_label}。" if voice.get() else "。") +
                       "语音模式已自动核对并备份同步配置；首次加载语音模型可能较慢。", "busy")
        except ValueError as error:
            messagebox.showerror("无法启动", str(error))
        except Exception:
            messagebox.showerror("无法启动", "无法建立受管进程。未关闭外部程序；请查看启动指南。")

    def tick():
        if manager.services and not state["failed"]:
            exited = [(name, service.process.poll()) for name, service in manager.services.items()
                      if service.process.poll() is not None]
            if exited:
                details = "、".join(f"{name}（退出码 {code}）" for name, code in exited)
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    set_component("console", "启动失败", "error")
                    set_component("voice", "进程已停止", "error")
                    set_component("speech", "进程已停止", "error")
                    set_component("browser", "未打开", "error")
                    set_status(
                        f"服务已退出：{details}。已停止其他受管服务。{_failure_hint(exited)}",
                        "error",
                    )
            elif manager.ready():
                if not state["opened"]:
                    state["opened"] = True
                    open_page()
                voxcpm_is_ready = (manager.voxcpm_ready()
                                    if manager.options.voice
                                    and manager.options.tts_backend == "voxcpm2" else False)
                if manager.options.voice and manager.options.tts_backend == "voxcpm2":
                    suffix = ("；VoxCPM2 与语音进程运行中" if voxcpm_is_ready
                              else "；VoxCPM2 正在加载，圆屏语音尚未就绪")
                else:
                    suffix = "；语音进程运行中，设备连接请在网页查看" if manager.options.voice else ""
                set_component("console", "已就绪", "good")
                set_component("voice", "小智进程运行" if manager.options.voice else "本次未启用",
                              "good" if manager.options.voice else "idle")
                if manager.options.voice and manager.options.tts_backend == "voxcpm2":
                    set_component("speech", "VoxCPM2 已就绪" if voxcpm_is_ready else "VoxCPM2 加载中",
                                  "good" if voxcpm_is_ready else "busy")
                elif manager.options.voice:
                    set_component("speech", "EdgeTTS 已选择", "good")
                else:
                    set_component("speech", "本次未启用")
                set_component("browser", "已请求打开" if state["opened"] else "尚未打开",
                              "good" if state["opened"] else "busy")
                set_status("控制台已就绪" + suffix + "。请在聊天页查看或检测模型状态；关闭网页不会停止服务。", "good")
                manager.publish_status(
                    "ready",
                    console_ready=True,
                    voxcpm_ready=voxcpm_is_ready,
                )
            elif time.monotonic() - state["started"] > 90:
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    set_component("console", "就绪超时", "error")
                    set_component("voice", "进程已停止", "error")
                    set_component("speech", "进程已停止", "error")
                    set_component("browser", "未打开", "error")
                    set_status("90 秒内未确认控制台就绪，已停止受管服务；未停止其他程序。请查看指南。", "error")
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
    ttk.Button(buttons, text="清理遗留语音", command=close_external_voice, style="Secondary.TButton").pack(side="left", padx=8)
    ttk.Button(buttons, text="使用指南", command=lambda: os.startfile(ROOT / "docs/guides/统一启动.md"), style="Secondary.TButton").pack(side="right", padx=(8, 0))
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(500, tick)
    try:
        window.mainloop()
    finally:
        manager.stop()
        lock.close()


if __name__ == "__main__":
    main()

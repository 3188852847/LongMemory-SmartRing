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
    load_preferences,
    save_preferences,
)
from firewall_panel import open_panel
from tts import config_action as tts_config_action


APP_BACKGROUND = "#f5f6fa"
CARD_BACKGROUND = "#ffffff"
ACCENT = "#a72760"


def _summary_text(voice, start_page, role, extraction, retrieval, tts, allow_delete, consolidation):
    """把内部启动枚举翻译为日常首页可理解的三行摘要。"""
    mode = "网页＋圆屏语音" if voice else "网页文字聊天"
    page_label = {"chat": "聊天", "device": "设备状态", "memories": "记忆管理", "settings": "设置中心"}[start_page]
    role_label = "爱莉希雅风格" if role == "elysia_v1" else "普通助手"
    extraction_label = "模型辅助提取" if extraction == "llm" else "规则提取"
    retrieval_label = "关键词＋语义召回" if retrieval == "hybrid" else "关键词召回"
    sound_label = "VoxCPM2 本地声音" if tts == "voxcpm2" else "EdgeTTS 联网声音"
    delete_label = "允许单条删除" if allow_delete else "不开放删除"
    consolidation_label = "低频整理已开启" if consolidation else "低频整理关闭"
    return (
        f"{mode}  ·  打开{page_label}  ·  {role_label}\n"
        f"{extraction_label}  ·  {retrieval_label}  ·  {sound_label}\n"
        f"{delete_label}  ·  {consolidation_label}"
    )


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
    window.geometry("920x740")
    window.minsize(720, 500)
    window.configure(background=APP_BACKGROUND)
    style = ttk.Style(window)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("App.TFrame", background=APP_BACKGROUND)
    style.configure("Page.TFrame", background=APP_BACKGROUND)
    style.configure("Header.TFrame", background=APP_BACKGROUND)
    style.configure("TLabel", font=("Microsoft YaHei UI", 9))
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
    style.configure("Eyebrow.TLabel", foreground=ACCENT, font=("Microsoft YaHei UI", 9, "bold"))
    style.configure("Subtitle.TLabel", foreground="#667085")
    style.configure("Hint.TLabel", foreground="#667085", font=("Microsoft YaHei UI", 9))
    style.configure("Summary.TLabel", font=("Microsoft YaHei UI", 10), foreground="#303747")
    style.configure("StatusIdle.TLabel", foreground="#98a2b3", font=("Microsoft YaHei UI", 12))
    style.configure("StatusBusy.TLabel", foreground="#d48806", font=("Microsoft YaHei UI", 12))
    style.configure("StatusGood.TLabel", foreground="#389e0d", font=("Microsoft YaHei UI", 12))
    style.configure("StatusError.TLabel", foreground="#cf1322", font=("Microsoft YaHei UI", 12))
    style.configure("Primary.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(18, 10))
    style.configure("Secondary.TButton", padding=(12, 8))
    style.configure("Section.TLabelframe", padding=14, background=CARD_BACKGROUND)
    style.configure("Section.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
    try:
        lock = Singleton()
    except ValueError as error:
        window.withdraw()
        messagebox.showinfo("已有启动面板或端口占用", str(error))
        window.destroy()
        return
    manager = Manager()
    box = ttk.Frame(window, padding=(30, 24), style="App.TFrame")
    box.pack(fill="both", expand=True)
    choice_path = ROOT / 'data/control/launcher.json'
    saved = load_preferences(choice_path)
    header = ttk.Frame(box, style="Header.TFrame")
    header.pack(fill="x", pady=(0, 18))
    ttk.Label(header, text="个人陪伴控制台", style="Eyebrow.TLabel").pack(anchor="w")
    ttk.Label(header, text="LongMemory", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        header,
        text="启动一次，就可以使用文字聊天和 SmartRing-Plus 圆屏；常用选择保存在本机。",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(3, 0))
    tabs = ttk.Notebook(box)
    tabs.pack(fill="both", expand=True)
    daily_tab, daily, daily_canvas = _scrollable_tab(tabs)
    advanced_tab, advanced, advanced_canvas = _scrollable_tab(tabs)
    tabs.add(daily_tab, text="日常启动")
    tabs.add(advanced_tab, text="高级设置")

    def scroll_current_tab(event):
        """鼠标位于面板任意控件上时，滚动当前可见页签。"""
        canvas = daily_canvas if tabs.index("current") == 0 else advanced_canvas
        if not event.delta:
            return
        units = -int(event.delta / 120)
        canvas.yview_scroll(units if units else (-1 if event.delta > 0 else 1), "units")

    window.bind_all("<MouseWheel>", scroll_current_tab, add="+")

    voice = tk.BooleanVar(value=saved["voice"])
    start_page_labels = {"聊天": "chat", "设备状态": "device", "记忆管理": "memories", "设置中心": "settings"}
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
    ttk.Label(mode_box, text="同时启动小智；圆屏在线状态仍在网页内查看。", style="Hint.TLabel").pack(anchor="w", padx=(24, 0), pady=(0, 2))
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
                     tts_backend, allow_memory_delete, memory_consolidation):
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

    def set_status(message, tone="idle"):
        """状态颜色只帮助扫读；完整文字仍是故障判断的唯一依据。"""
        styles = {"idle": "StatusIdle.TLabel", "busy": "StatusBusy.TLabel",
                  "good": "StatusGood.TLabel", "error": "StatusError.TLabel"}
        status.set(message)
        status_indicator.configure(style=styles.get(tone, "StatusIdle.TLabel"))
    buttons = ttk.Frame(daily)
    buttons.pack(fill="x", pady=(8, 0))
    state = {"opened": False, "started": 0.0, "failed": False}

    def open_page():
        if manager.ready():
            webbrowser.open(console_url(manager.options.port, start_page_labels[start_page.get()]))
        else:
            messagebox.showinfo("尚未就绪", "请先启动并等待控制台就绪。")

    def stop(confirm=True):
        if manager.services and confirm and not messagebox.askyesno("停止本面板启动的服务？",
                "请先结束聊天。停止会中断当前回答/语音，未完成操作可能已写入；不会删除数据库。"):
            return False
        try:
            manager.stop()
        except Exception:
            set_status("停止未完全确认，请关闭面板并检查服务，不要重复启动。", "error")
            return False
        state.update(opened=False, failed=False)
        start_button.config(state="normal")
        set_status("已停止本面板启动的服务；其他终端启动的程序未被停止。")
        return True

    def start():
        try:
            if voice.get():
                info = config_action(Path(server.get()), ip.get().strip())
                if info['changed']:
                    raise ValueError(f"小智配置仍为 {info['old_ip']}，请先点击同步小智地址。")
                voice_config = tts_config_action(Path(server.get()), ROOT, selected_tts())
                if not voice_config["config_matches"]:
                    raise ValueError("小智 TTS 配置与所选声音不一致，请先点击“检查并同步”。")
            options = Options(database=Path(database.get()), voice=voice.get(), voice_root=Path(server.get()),
                              lan_ip=ip.get().strip(), role=role.get(), consent=consent.get(),
                              tts_backend=selected_tts(),
                              memory_extraction=selected_extraction(),
                              memory_retrieval=selected_retrieval(),
                              enable_memory_consolidation=memory_consolidation.get(),
                              allow_memory_delete=allow_memory_delete.get(),
                              embedding_model_dir=Path(embedding_model.get()))
            manager.start(options)
            try:
                save_preferences(choice_path, current_preferences())
            except OSError:
                settings_status.set("服务已启动，但本机首选项未保存；下次仍可手动选择。")
            state.update(started=time.monotonic(), opened=False, failed=False)
            start_button.config(state="disabled")
            set_status("正在启动；首次加载语音模型可能较慢。尚未验证学校模型或圆屏连接。", "busy")
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
                    hint = "语音代码 3 表示共享路径或配置检查失败。" if ("voice", 3) in exited else ""
                    set_status(f"服务已退出：{details}。已停止其他受管服务。{hint}请按指南核对环境、配置和端口。", "error")
            elif manager.ready():
                if not state["opened"]:
                    state["opened"] = True
                    open_page()
                if manager.options.voice and manager.options.tts_backend == "voxcpm2":
                    suffix = ("；VoxCPM2 与语音进程运行中" if manager.voxcpm_ready()
                              else "；VoxCPM2 正在加载，圆屏语音尚未就绪")
                else:
                    suffix = "；语音进程运行中，设备连接请在网页查看" if manager.options.voice else ""
                set_status("控制台已就绪" + suffix + "。学校模型未探测。保留此面板，关闭网页不会停止服务。", "good")
            elif time.monotonic() - state["started"] > 90:
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    set_status("90 秒内未确认控制台就绪，已停止受管服务；未停止其他程序。请查看指南。", "error")
        window.after(1000, tick)

    def close():
        if stop():
            lock.close()
            window.destroy()

    start_button = ttk.Button(buttons, text="启动并打开控制台", command=start, style="Primary.TButton")
    start_button.pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="重新打开网页", command=open_page, style="Secondary.TButton").pack(side="left", padx=8)
    ttk.Button(buttons, text="停止服务", command=lambda: stop(False), style="Secondary.TButton").pack(side="left", padx=8)
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

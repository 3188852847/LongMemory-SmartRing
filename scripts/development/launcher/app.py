"""无新增依赖的 Windows 日常启动面板；服务生命周期属于这个窗口。"""

import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser
from pathlib import Path

from runtime import Manager, Options, ROOT, Singleton, VOICE_ROOT, console_url
from network import local_addresses, config_action, load_choice, save_choice
from firewall_panel import open_panel
from tts import config_action as tts_config_action


def main():
    window = tk.Tk()
    window.title("LongMemory · 日常启动")
    window.geometry("820x730")
    window.minsize(760, 700)
    try:
        lock = Singleton()
    except ValueError as error:
        window.withdraw()
        messagebox.showinfo("已有启动面板或端口占用", str(error))
        window.destroy()
        return
    manager = Manager()
    box = ttk.Frame(window, padding=20)
    box.pack(fill="both", expand=True)
    ttk.Label(box, text="LongMemory 日常启动", font=("Microsoft YaHei UI", 18)).pack(anchor="w")
    ttk.Label(box, text="复用当前配置，不安装依赖、不改数据库、不设置开机自启。", wraplength=710).pack(anchor="w", pady=8)
    voice = tk.BooleanVar(value=False)
    consent = tk.BooleanVar(value=False)
    database = tk.StringVar(value=str(ROOT / "data/databases/xiaozhi-demo-v1.db"))
    server = tk.StringVar(value=str(VOICE_ROOT))
    choice_path = ROOT / 'data/control/launcher.json'
    ip = tk.StringVar(value=load_choice(choice_path))
    role = tk.StringVar(value="elysia_v1")
    tts_backend = tk.StringVar(value="EdgeTTS（联网标准音色）")
    ttk.Checkbutton(box, text="同时启动圆屏语音（默认只启动文字聊天）", variable=voice).pack(anchor="w")
    for label, variable in [("日常数据库（已有文件）", database), ("小智目录（仅语音模式）", server)]:
        ttk.Label(box, text=label).pack(anchor="w", pady=(8, 0))
        ttk.Entry(box, textvariable=variable).pack(fill="x")
    ttk.Label(box, text='电脑局域网 IP（多网卡时请选择圆屏能访问的地址）').pack(anchor='w', pady=(8, 0))
    address_row = ttk.Frame(box)
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
                save_choice(choice_path, selected)
                network_status.set(f'已同步。圆屏 OTA：http://{selected}:8003/xiaozhi/ota/；防火墙见指南。')
        except (ValueError, OSError) as error:
            messagebox.showerror('未完成同步', str(error))

    ttk.Button(address_row, text='刷新地址', command=refresh).pack(side='left', padx=8)
    ttk.Button(address_row, text='同步小智地址', command=sync_address).pack(side='left')
    ttk.Button(address_row, text='网络与防火墙', command=lambda: open_panel(window, ip.get(), ROOT)).pack(side='left', padx=8)
    ttk.Label(box, textvariable=network_status, wraplength=710).pack(anchor='w', pady=8)
    refresh()
    row = ttk.Frame(box)
    row.pack(fill="x", pady=8)
    ttk.Label(row, text="网页角色：").pack(side="left")
    ttk.Combobox(row, textvariable=role, values=("elysia_v1", "plain_v1"), state="readonly", width=18).pack(side="left")
    ttk.Label(row, text="  不自动改变小智角色；控制台端口 8767").pack(side="left")
    tts_row = ttk.Frame(box)
    tts_row.pack(fill="x", pady=8)
    ttk.Label(tts_row, text="圆屏声音：").pack(side="left")
    ttk.Combobox(tts_row, textvariable=tts_backend,
                 values=("EdgeTTS（联网标准音色）", "VoxCPM2（本地 plain）"),
                 state="readonly", width=27).pack(side="left")

    def selected_tts():
        return "voxcpm2" if tts_backend.get().startswith("VoxCPM2") else "edge"

    def sync_tts():
        if manager.services:
            messagebox.showinfo("请先停止", "请先停止本面板服务；也请结束外部终端中的小智服务。")
            return
        try:
            backend = selected_tts()
            checked = tts_config_action(Path(server.get()), ROOT, backend)
            if checked["config_matches"]:
                messagebox.showinfo("无需同步", "小智磁盘配置已经匹配；运行中是否生效仍需重启验证。")
                return
            label = "VoxCPM2 本地声音" if backend == "voxcpm2" else "EdgeTTS"
            if messagebox.askyesno("同步圆屏声音？",
                    f"将小智 TTS 切换为 {label}。\n只修改 TTS 选择与固定接口字段，原配置会备份；不会启动服务。"):
                tts_config_action(Path(server.get()), ROOT, backend, apply=True,
                                  expected_digest=checked["digest"])
                messagebox.showinfo("同步完成", "磁盘配置已更新；下次启动小智加载，实机效果仍需试听。")
        except (ValueError, OSError, KeyError):
            messagebox.showerror("未完成同步", "TTS 配置检查或同步失败；未显示私有配置内容。")

    ttk.Button(tts_row, text="检查并同步", command=sync_tts).pack(side="left", padx=8)
    tk.Checkbutton(box, variable=consent, anchor="w", justify="left",
                    text="我了解：聊天会写入记忆；当前 HTTP 会明文发送凭据与内容，仅用非敏感合成体验。",
                    wraplength=710).pack(anchor="w", pady=8)
    status = tk.StringVar(value="尚未启动。学校模型是否可用需你在校园网自行验证。")
    ttk.Label(box, textvariable=status, wraplength=710).pack(anchor="w", pady=10)
    buttons = ttk.Frame(box)
    buttons.pack(fill="x")
    state = {"opened": False, "started": 0.0, "failed": False}

    def open_page():
        if manager.ready():
            webbrowser.open(console_url(manager.options.port))
        else:
            messagebox.showinfo("尚未就绪", "请先启动并等待控制台就绪。")

    def stop(confirm=True):
        if manager.services and confirm and not messagebox.askyesno("停止本面板启动的服务？",
                "请先结束聊天。停止会中断当前回答/语音，未完成操作可能已写入；不会删除数据库。"):
            return False
        try:
            manager.stop()
        except Exception:
            status.set("停止未完全确认，请关闭面板并检查服务，不要重复启动。")
            return False
        state.update(opened=False, failed=False)
        start_button.config(state="normal")
        status.set("已停止本面板启动的服务；其他终端启动的程序未被停止。")
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
                              tts_backend=selected_tts())
            manager.start(options)
            state.update(started=time.monotonic(), opened=False, failed=False)
            start_button.config(state="disabled")
            status.set("正在启动；首次加载语音模型可能较慢。尚未验证学校模型或圆屏连接。")
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
                    status.set(f"服务已退出：{details}。已停止其他受管服务。{hint}请按指南核对环境、配置和端口。")
            elif manager.ready():
                if not state["opened"]:
                    state["opened"] = True
                    open_page()
                if manager.options.voice and manager.options.tts_backend == "voxcpm2":
                    suffix = ("；VoxCPM2 与语音进程运行中" if manager.voxcpm_ready()
                              else "；VoxCPM2 正在加载，圆屏语音尚未就绪")
                else:
                    suffix = "；语音进程运行中，设备连接请在网页查看" if manager.options.voice else ""
                status.set("控制台已就绪" + suffix + "。学校模型未探测。保留此面板，关闭网页不会停止服务。")
            elif time.monotonic() - state["started"] > 90:
                stopped = stop(False)
                state["failed"] = True
                if stopped:
                    status.set("90 秒内未确认控制台就绪，已停止受管服务；未停止其他程序。请查看指南。")
        window.after(1000, tick)

    def close():
        if stop():
            lock.close()
            window.destroy()

    start_button = ttk.Button(buttons, text="启动", command=start)
    start_button.pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="打开控制台", command=open_page).pack(side="left", padx=8)
    ttk.Button(buttons, text="停止服务", command=stop).pack(side="left", padx=8)
    ttk.Button(buttons, text="使用指南", command=lambda: os.startfile(ROOT / "docs/guides/统一启动.md")).pack(side="left", padx=8)
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(500, tick)
    try:
        window.mainloop()
    finally:
        manager.stop()
        lock.close()


if __name__ == "__main__":
    main()

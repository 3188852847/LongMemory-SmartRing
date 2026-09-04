"""无新增依赖的 Windows 日常启动面板；服务生命周期属于这个窗口。"""

import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser
from pathlib import Path

from runtime import Manager, Options, ROOT, Singleton, VOICE_ROOT


def main():
    window = tk.Tk()
    window.title("LongMemory · 日常启动")
    window.geometry("820x600")
    window.minsize(760, 560)
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
    ip = tk.StringVar(value="192.168.124.45")
    role = tk.StringVar(value="elysia_v1")
    ttk.Checkbutton(box, text="同时启动圆屏语音（默认只启动文字聊天）", variable=voice).pack(anchor="w")
    for label, variable in [("日常数据库（已有文件）", database), ("小智目录（仅语音模式）", server),
                            ("电脑局域网 IP（仅语音模式，须与配置一致）", ip)]:
        ttk.Label(box, text=label).pack(anchor="w", pady=(8, 0))
        ttk.Entry(box, textvariable=variable).pack(fill="x")
    row = ttk.Frame(box)
    row.pack(fill="x", pady=8)
    ttk.Label(row, text="网页角色：").pack(side="left")
    ttk.Combobox(row, textvariable=role, values=("elysia_v1", "plain_v1"), state="readonly", width=18).pack(side="left")
    ttk.Label(row, text="  不自动改变小智角色；控制台端口 8767").pack(side="left")
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
            webbrowser.open(f"http://127.0.0.1:{manager.options.port}/chat")
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
            options = Options(database=Path(database.get()), voice=voice.get(), voice_root=Path(server.get()),
                              lan_ip=ip.get().strip(), role=role.get(), consent=consent.get())
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

"""本机搜索配置窗口；输入不回显、不联网验证，不把密钥带到命令行。"""

from pathlib import Path
import os
import sys

from voice_web_config import CONFIG_PATH, load_config, save_config


def open_search_configuration(parent=None, path=CONFIG_PATH):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Toplevel(parent) if parent is not None else tk.Tk()
    window.title("圆屏联网搜索配置")
    window.geometry("540x285")
    body = ttk.Frame(window, padding=20)
    body.pack(fill="both", expand=True)
    labels = {"Tavily": "tavily", "秘塔": "metaso", "关闭联网搜索": "disabled"}
    try:
        saved = load_config(path)
        selected = next(k for k, v in labels.items() if v == saved.provider)
        note = "已保存密钥，不回显；同一供应商留空可保留。" if saved.api_key else "尚未配置搜索密钥。"
    except (OSError, ValueError):
        selected, note = "Tavily", "配置文件格式无效，保存前需修复；不会覆盖未知内容。"
    provider = tk.StringVar(value=selected if selected != "关闭联网搜索" else "Tavily")
    secret, status = tk.StringVar(), tk.StringVar(value=note)
    ttk.Label(body, text="供应商").pack(anchor="w")
    ttk.Combobox(body, textvariable=provider, values=tuple(labels), state="readonly").pack(fill="x", pady=(3, 10))
    ttk.Label(body, text="API Key（只保存本机，不要发到聊天中）").pack(anchor="w")
    ttk.Entry(body, textvariable=secret, show="*").pack(fill="x", pady=(3, 10))
    ttk.Label(body, textvariable=status, wraplength=495).pack(anchor="w")
    ttk.Label(body, text="实时优先下，保存后下一轮生效；仅开放网页搜索，不执行网站操作。",
              wraplength=495).pack(anchor="w", pady=8)

    def save():
        try:
            save_config(path, provider=labels[provider.get()], api_key=secret.get().strip())
        except (OSError, ValueError):
            status.set("未保存：请核对供应商、密钥格式和本机文件权限。")
            return
        secret.set("")
        status.set("已保存到本机。尚未验证账号和网络；下一轮查询将使用该配置。")
    ttk.Button(body, text="保存配置", command=save).pack(anchor="e", pady=8)
    if parent is None:
        window.mainloop()
    return window


if __name__ == "__main__":
    # 与项目面板一致，从 UTF-8 venv 元数据定位含中文路径的现有 Tcl 资源。
    config = Path(sys.prefix) / "pyvenv.cfg"
    if sys.platform == "win32" and config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            if line.startswith("home = "):
                base = Path(line.split("=", 1)[1].strip()) / "tcl"
                for name, sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
                    os.environ.setdefault(name, str(base / sub))
    open_search_configuration()

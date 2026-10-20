"""独立小窗口，后台等待系统查询/UAC，不阻塞主启动面板。"""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from firewall import inspect, change, scope


def open_panel(parent, address, root, *, ws_port=8000, http_port=8003):
    if (ws_port, http_port) != (8000, 8003):
        messagebox.showinfo('独立圆屏端口', f'本项目使用 {ws_port}/{http_port}，壁纸仍为8768。旧面板仅支持默认端口规则，未查询或修改规则。请先核对新端口监听和现有防火墙范围。', parent=parent)
        return
    window = tk.Toplevel(parent)
    window.title('圆屏网络与防火墙')
    window.geometry('740x420')
    box = ttk.Frame(window, padding=18)
    box.pack(fill='both', expand=True)
    ttk.Label(box, text='已经能用圆屏聊天，就不需要添加规则。这里只管理本项目规则。', wraplength=690).pack(anchor='w')
    ip = tk.StringVar(value=address)
    subnet = tk.StringVar(value='')
    for title, variable in [('电脑局域网 IP', ip), ('允许的圆屏 IP 或网段（不自动猜测；此前校园网为 192.168.120.0/21）', subnet)]:
        ttk.Label(box, text=title, wraplength=690).pack(anchor='w', pady=(10, 0))
        ttk.Entry(box, textvariable=variable).pack(fill='x')
    status = tk.StringVar(value='尚未检查。查询失败会显示未知，不当作规则不存在。')
    ttk.Label(box, textvariable=status, wraplength=690).pack(anchor='w', pady=16)
    row = ttk.Frame(box)
    row.pack(fill='x')
    results = queue.Queue()
    buttons = []
    busy = False

    def perform(action):
        nonlocal busy
        selected, remote = ip.get().strip(), subnet.get().strip()
        if action != 'Check':
            try:
                if action == 'Allow':
                    selected, remote = scope(selected, remote)
            except ValueError as error:
                messagebox.showerror('范围无效', str(error), parent=window)
                return
            detail = (f'允许 {remote} 访问 {selected} 的 TCP 8000/8003，以及短时壁纸投递端口 8768；分别绑定实际监听 Python。\n不会覆盖已有项目规则。'
                      if action == 'Allow' else '仅撤销 LongMemory 的语音与壁纸演示规则。圆屏可能断连；其他规则不变。')
            if not messagebox.askyesno('确认修改系统防火墙', detail + '\n随后弹出 Windows 管理员授权。', parent=window):
                return
        busy = True
        for button in buttons:
            button.config(state='disabled')
        status.set('正在查询……' if action == 'Check' else '等待管理员授权/操作完成，请留意 Windows 授权提示……')

        def work():
            try:
                if action == 'Check':
                    data = inspect(selected)
                    ports = ', '.join(map(str, data['ports'])) or '无'
                    rules = data['rules']
                    description = '项目规则不存在；不代表防火墙阻止连接，其他规则可能已允许。'
                    if rules:
                        description = '; '.join(f"{r['name']}：启用={r['enabled']}，本地={r['local']}，来源={r['remote']}" for r in rules)
                        if any(selected not in r['local'] for r in rules):
                            description += ' 当前 IP 与规则不匹配，请核对后显式撤销旧规则、再添加。'
                    results.put(f'所选地址监听端口：{ports}。\n{description}\n仅检查电脑侧；圆屏在线状态请看控制台设备页。')
                else:
                    results.put(change(action, selected, remote, root))
            except Exception as error:
                results.put(str(error) if isinstance(error, ValueError) else '操作无法完成，状态未知；请检查网络或权限。')
        threading.Thread(target=work, daemon=True).start()

    def poll():
        nonlocal busy
        try:
            status.set(results.get_nowait())
            busy = False
            for button in buttons:
                button.config(state='normal')
        except queue.Empty:
            pass
        window.after(200, poll)

    for title, action in [('检查监听与规则', 'Check'), ('添加圆屏放行规则', 'Allow'), ('撤销本项目规则', 'Revoke')]:
        button = ttk.Button(row, text=title, command=lambda a=action: perform(a))
        button.pack(side='left', padx=5)
        buttons.append(button)
    window.protocol('WM_DELETE_WINDOW', lambda: messagebox.showinfo('操作进行中', '请先完成或取消系统授权。', parent=window) if busy else window.destroy())
    window.after(200, poll)

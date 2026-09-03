"""独立进程客户端：固定访问本机，令牌读文件，不进命令行/输出/浏览器。"""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from control_http import PORT, TOKEN_FILE, read_token


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不向重定向目标转发管理令牌。


def request_control(action, volume=None):
    token = read_token(TOKEN_FILE)
    path = "/api/device" if action == "status" else "/api/device/volume"
    body = json.dumps({"volume": volume}).encode() if action == "set-volume" else None
    request = Request(f"http://127.0.0.1:{PORT}{path}", data=body,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"})
    # 忽略系统代理，以免本机令牌或控制请求被送往外部代理。
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, json.loads(response.read(16384))
    except HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read(16384))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "read-volume", "set-volume"])
    parser.add_argument("volume", nargs="?", type=int)
    args = parser.parse_args(argv)
    if args.action == "set-volume":
        if args.volume is None or not 5 <= args.volume <= 60:
            parser.error("set-volume 必须指定 5 到 60 的整数，验证阶段不允许静音或高音量。")
    elif args.volume is not None:
        parser.error("只有 set-volume 接受音量参数。")
    try:
        status, result = request_control(args.action, args.volume)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "set-volume" and not result.get("verified"):
            print("未完成音量读回确认；可能已经改变，请先 read-volume，不要自动重试。")
        return 0 if status == 200 and (args.action != "set-volume" or result.get("verified")) else 1
    except FileNotFoundError:
        print("未找到控制令牌；先用 --device-control 启动小智。", file=sys.stderr)
    except (OSError, ValueError, URLError):
        print("本机控制请求失败；检查服务、端口和令牌文件。请求可能已送达，请勿盲目重试写操作。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""圆屏项目的两个 LAN 端口契约；与 Docker 和内部回环服务分离。"""

DEFAULT_WS_PORT = 8000
DEFAULT_HTTP_PORT = 8003
INTERNAL_PORTS = {8766, 8767, 8768, 18767, 18768, 18769, 18770}


def validate_voice_ports(ws_port=DEFAULT_WS_PORT, http_port=DEFAULT_HTTP_PORT, *, console_port=8767):
    if any(type(value) is not int or not 1024 <= value <= 65535 for value in (ws_port, http_port)):
        raise ValueError('圆屏端口必须是 1024–65535 的整数。')
    if ws_port == http_port or any(value in INTERNAL_PORTS | {console_port} for value in (ws_port, http_port)):
        raise ValueError('圆屏端口必须互异，且不能占用项目内部端口。')
    return ws_port, http_port


def port_arguments(ws_port, http_port):
    validate_voice_ports(ws_port, http_port)
    return ['--voice-ws-port', str(ws_port), '--voice-http-port', str(http_port)]

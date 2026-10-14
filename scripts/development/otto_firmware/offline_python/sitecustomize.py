"""Child-process guard: allow local sockets, fail external network acquisition."""
import socket
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_getaddrinfo = socket.getaddrinfo
def local(address):
    return not isinstance(address, tuple) or address[0] in ('127.0.0.1', '::1', 'localhost')
def connect(self, address):
    if not local(address): raise OSError('0014 offline build: external socket blocked')
    return _connect(self, address)
def connect_ex(self, address):
    if not local(address): raise OSError('0014 offline build: external socket blocked')
    return _connect_ex(self, address)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
def getaddrinfo(host, *args, **kwargs):
    if host not in (None, '127.0.0.1', '::1', 'localhost'):
        raise socket.gaierror('0014 offline build: external DNS blocked')
    return _getaddrinfo(host, *args, **kwargs)
socket.getaddrinfo = getaddrinfo

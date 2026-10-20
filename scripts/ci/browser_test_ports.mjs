// 合成主机不得占用日用控制、Runtime、语音或模型服务的已知端口。
const dailyPorts=new Set([8000,8003,8766,8767,8768,18000,18003,18767,18770]);

export function testPort(value,fallback) {
  const port=Number(value ?? fallback);
  if(!Number.isInteger(port)||port<1024||port>65535||dailyPorts.has(port))throw new Error('需要独立的合成测试端口');
  return port;
}

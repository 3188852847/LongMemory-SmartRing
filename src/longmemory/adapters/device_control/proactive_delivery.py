"""把主动交流投递端口适配到受限的小智本机控制桥。"""

from datetime import datetime

from longmemory.application.proactive import DeliveryQueueResult, DeliveryQueueStatus

from .xiaozhi import BridgeError, XiaozhiControlClient


class XiaozhiProactiveDelivery:
    """不拥有客户端生命周期；由控制台启动与关闭共享客户端。"""

    def __init__(self, client: XiaozhiControlClient) -> None:
        self._client = client

    async def queue(self, content: str, expires_at: datetime) -> DeliveryQueueResult:
        try:
            await self._client.announce(content, expires_at)
        except BridgeError as error:
            # BridgeError 已经只包含白名单稳定码，可安全进入结果账本。
            return DeliveryQueueResult(DeliveryQueueStatus.FAILED, error.code)
        return DeliveryQueueResult(
            DeliveryQueueStatus.ACCEPTED,
            "xiaozhi_queue_accepted",
        )

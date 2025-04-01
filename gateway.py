import grpc
import asyncio
from concurrent import futures
from typing import Dict, AsyncIterable, Optional
import acp_pb2
import acp_pb2_grpc


class ConnectionPool:
    """gRPC连接池管理"""
    def __init__(self):
        self._channels: Dict[str, grpc.aio.Channel] = {}
        self._stubs: Dict[str, acp_pb2_grpc.AgentServiceStub] = {}

    async def get_stub(self, address: str) -> Optional[acp_pb2_grpc.AgentServiceStub]:
        """获取或创建指定地址的存根"""
        if address not in self._channels:
            try:
                channel = grpc.aio.insecure_channel(address)
                await channel.channel_ready()
                self._channels[address] = channel
                self._stubs[address] = acp_pb2_grpc.AgentServiceStub(channel)
            except grpc.RpcError as e:
                print(f"Connection failed to {address}: {e.code()}")
                return None
        return self._stubs[address]

    async def close_all(self):
        """关闭所有连接"""
        closing_tasks = []
        for addr, channel in self._channels.items():
            closing_tasks.append(channel.close())
        await asyncio.gather(*closing_tasks, return_exceptions=True)
        self._channels.clear()
        self._stubs.clear()

class Gateway(acp_pb2_grpc.GatewayServiceServicer):
    def __init__(self):
        self.agent_registry: Dict[str, acp_pb2.RouteInfo] = {}
        self.connection_pool = ConnectionPool()

    async def _forward_message(self, message: acp_pb2.MultiModalMessage) -> AsyncIterable[acp_pb2.MultiModalMessage]:
        """消息转发核心逻辑"""
        receiver_info = self.agent_registry.get(message.receiver_id)
        if not receiver_info:
            print(f"<GW>: Routing failed: Receiver {message.receiver_id} not found")
            return

        stub = await self.connection_pool.get_stub(receiver_info.address)

        try:
            # 调用流方法
            stream = stub.StreamCommunicate()

            # 发送原始消息
            await stream.write(message)

            # 处理响应流
            async for response in stream:
                yield response

        except grpc.RpcError as e:
            print(f"<GW>: Forwarding to {receiver_info.address} failed: {e.code()}")
            del self.agent_registry[message.receiver_id] # 移除失效节点
            return

    async def RouteMessage(self, request_iterator: AsyncIterable[acp_pb2.MultiModalMessage],
                           context) -> AsyncIterable[acp_pb2.MultiModalMessage]:
        """消息路由主入口"""
        async for message in request_iterator:
            # route 响应流
            async for response in self._forward_message(message):
                yield response

    async def RegisterAgent(self, request: acp_pb2.RouteInfo, context) -> acp_pb2.RegisterResponse:
        self.agent_registry[request.agent_id] = request
        print(f"<GW>: Register {request.agent_id} (addr in {request.address})")
        return acp_pb2.RegisterResponse(
            success=True,
            peers=list(self.agent_registry.values())
        )


async def serve_gateway(port: int = 50051):
    # 注册业务服务
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    acp_pb2_grpc.add_GatewayServiceServicer_to_server(Gateway(), server)

    # 启动服务
    listen_addr = f"[::]:{port}"
    server.add_insecure_port(listen_addr)
    await server.start()
    print(f"<GW>: Gateway serving on port {port}")
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(1)
import grpc
import asyncio
from typing import AsyncIterable, Dict
import acp_pb2
import acp_pb2_grpc


class BaseAgent(acp_pb2_grpc.AgentServiceServicer):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.server = None
        self.address = ""
        self.gateway_addr = ""
        self.peers: Dict[str, acp_pb2.RouteInfo] = {}

    async def handle_outgoing_message(self) -> acp_pb2.MultiModalMessage:
        """子类需要实现RouteMessage消息发送逻辑"""
        raise NotImplementedError

    async def handle_incoming_message(self, message: acp_pb2.MultiModalMessage):
        """子类需要实现RouteMessage消息接收逻辑"""
        raise NotImplementedError

    async def process_comm_message(self, message: acp_pb2.MultiModalMessage) -> acp_pb2.MultiModalMessage:
        """子类需要实现StreamCommunicate消息处理逻辑"""
        raise NotImplementedError

    async def _send_messages(self, stream):
        while True:
            message = await self.handle_outgoing_message()
            await stream.write(message)

    async def _receive_messages(self, stream):
        async for response in stream:
            await self.handle_incoming_message(response)

    async def _handle_route_message_stream(self, stream):
        send_task = asyncio.create_task(self._send_messages(stream))
        recv_task = asyncio.create_task(self._receive_messages(stream))
        try:
            await asyncio.gather(send_task, recv_task)
        except grpc.aio.AioRpcError as e:
            print(f"RPC Error: {e.details()}")
            if e.code() == grpc.StatusCode.UNKNOWN:
                # 处理 BrokenPipeError
                pass
        except Exception as e:
            print(f"其他异常: {str(e)}")

    async def StreamCommunicate(self, request_iterator: AsyncIterable[acp_pb2.MultiModalMessage],
                                context) -> AsyncIterable[acp_pb2.MultiModalMessage]:
        async for message in request_iterator:
            # 异步处理消息
            processed_msg = await self.process_comm_message(message)
            # 立即返回响应
            yield processed_msg

    async def connect_to_gateway(self, gateway_addr: str):
        self.gateway_addr = gateway_addr
        async with grpc.aio.insecure_channel(self.gateway_addr) as channel:
            stub = acp_pb2_grpc.GatewayServiceStub(channel)

            try:
                # 注册Agent
                response = await stub.RegisterAgent(acp_pb2.RouteInfo(
                    agent_id=self.agent_id,
                    address=self.address))
                self.peers = {peer.agent_id: peer for peer in response.peers}
                print(f"<{self.agent_id}>: RegisterResponse from GW ({gateway_addr})")
            except grpc.aio.AioRpcError as e:
                print(f"RPC Error: {e.details()}")
                if e.code() == grpc.StatusCode.UNKNOWN:
                    # 处理 BrokenPipeError
                    pass
            except Exception as e:
                print(f"其他异常: {str(e)}")

            # 建立RouteMessage双向流
            stream = stub.RouteMessage()
            await self._handle_route_message_stream(stream)

    async def start(self, port: int, gateway_addr: str):
        self.server = grpc.aio.server()
        acp_pb2_grpc.add_AgentServiceServicer_to_server(self, self.server)
        self.address = f'localhost:{port}'
        self.server.add_insecure_port(self.address)
        await self.server.start()
        print(f"<{self.agent_id}>: Agent {self.agent_id} started on {self.address}")

        asyncio.create_task(self.connect_to_gateway(gateway_addr))

        # 等待结束
        try:
            await self.server.wait_for_termination()
        finally:
            # 确保正确关闭服务器
            await self.server.stop(1)  # 1秒超时

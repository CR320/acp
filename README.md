# Agent Context Protocol

## gRPC通信

**消息流转示意图：**
```
Agent A                   Gateway                 Agent B
   |----MultiModalMessage--->|                       |
   |                         |----建立到B的连接------->|
   |                         |----转发消息----------->|
   |                         |<--------响应-- --------|
   |<------- 响应 ------------|                       |
```

## Setup
```
pip install -r requirements.txt
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. acp.proto
```
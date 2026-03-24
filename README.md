# Micro Action Recognition System

## 项目概述

- 目标：构建前后端分离的微动作识别系统。
- 当前阶段：系统联调与优化阶段（远程增强与本地适配已打通）。
- 当前模型状态：已接入 **VideoMambaPro Middle (16f)** 真实模型。
- 架构调整：采用 **分布式远程推理架构**（Local Windows GUI + Remote Linux GPU Server），通过 SSH 隧道实现跨平台高性能计算。

## 截止目前已完成工作

### 1) 分布式推理引擎（远程端 - Linux）

- **核心模型接入**：成功加载 `checkpoint-best.pth` 权重，支持 16 帧（16f）时序特征提取。
- **环境隔离技术**：利用 Linux 端已配置好的 Mamba 环境（`mamba-ssm`, `causal-conv1d`），解决 Windows 平台编译困难。
- **原生高性能后端**：开发了基于 `http.server` 的零依赖推理网关，支持 `multipart/form-data` 视频流接收。
- **预测精度对齐**：完整支持 52 类微动作英文标签。

### 2) 后端服务（FastAPI - 本机端）

- **代理推理逻辑**：`ModelService` 已从本地伪造数据切换为 **严格远程调用模式**。
- **协议适配完成**：已对齐远程 `probs/logits_raw/temporal_probs/attention_hotspots` 等增强字段。
- **级联可视化链路**：本地已基于远程 `attention_matrix + hotspots` 生成热力图叠加与红框展示，时序曲线读取真实 `temporal_probs`。
- **导出代理能力**：本地后端新增远程导出代理接口，支持触发 `/render_expert_video` 并通过本地路由下载导出视频。
- **调试监控**：增加控制台 DEBUG 模式，可实时查看远程返回的原始信息与时序来源。

### 3) 前端页面（Vue + Vite）

- **动作映射支持**：支持 52 类动作的英文标签动态渲染。
- **链路反馈增强**：支持显示远程服务器状态（`Verified Inference by REMOTE Linux Server`）。
- **可读性增强**：支持显示注意力来源/钩子模式/归一化模式/热点阈值。
- **导出能力接入**：新增“导出专家视频”按钮，支持一键触发导出并下载结果。

### 4) 系统联调与工程化

- **SSH 隧道方案**：验证了 `9000 -> 9000` 端口转发的稳定性。
- **移除随机兜底**：关闭了 `fallback` 逻辑，确保 UI 显示结果均来自真实模型。

## 目录结构

- `backend/`：本机运行环境（Windows），处理业务逻辑与可视化
- `frontend/`：本机运行环境（Vue），处理交互展示
- `remote_inference_server.py`：部署在服务器（Linux）的推理引擎
- `REMOTE_INFERENCE_GUIDE.md`：详细的分布式部署配置指导

## 运行环境要求

### 后端 (本机)

- 操作系统：Windows
- Python：建议 3.10（推荐）
- 环境管理：Anaconda

### 推理机 (服务器)

- 操作系统：Linux
- 环境要求：CUDA + Mamba-SSM 环境

### 前端

- Node.js：20.19+ (Vite 7)

## 日常运行（每次开发）

### Step 1: 启动服务器端 (Linux)

```bash
python remote_inference_server.py
```

### Step 2: 建立通信链路 (Windows Terminal)

```bash
ssh -L 9000:localhost:9000 xxx@xxx.xxx.x.xxx
```

### Step 3: 手动启动本地应用 (推荐)

终端 1（后端）：

```bash
cd /d d:\Project\Micro_Action_Recognition_System
conda activate Micro_Action
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

```

终端 2（前端）：

```bash
cd /d d:\Project\Micro_Action_Recognition_System\frontend
npm run dev
```

访问地址：

- 后端 API：http://127.0.0.1:8000
- 前端页面：http://127.0.0.1:5173

### 方式 2：VS Code Tasks

- `Backend: Install Requirements (conda Micro_Action)`
- `Backend: Run API (conda Micro_Action)`
- `Frontend: Install Dependencies`
- `Frontend: Run Dev Server`

## 常见问题

### 1) `pip install -r requirements.txt` 找不到文件

请在项目根目录执行：

```bash
pip install -r backend/requirements.txt
```

### 2) 出现 `pydantic-core` 构建失败（日志含 `cp314`）

这是 Python 3.14 兼容性问题，建议重建为 Python 3.10 环境：

```bash
conda deactivate
conda remove -n Micro_Action --all -y
conda create -n Micro_Action python=3.10 -y
conda activate Micro_Action
pip install -r backend/requirements.txt
```

### 3) 前端上传后显示 `Network Error`

优先检查后端是否已启动并可访问：

```bash
http://127.0.0.1:8000/health
```

若能返回 `{"status":"ok"}`，说明网络链路正常；若不能，先排查后端启动日志。

### 4) 后端启动出现 `No module named 'app'`

当前代码已修复该问题；请确保使用本 README 给出的启动命令，不要混用旧命令或错误工作目录。

## 达标检查表（系统集成与可视化）

| 模块       | 验收项                                       | 当前状态                                  | 结论           | 下一动作                                     |
| ---------- | -------------------------------------------- | ----------------------------------------- | -------------- | -------------------------------------------- |
| 模型推理   | 替换 fallback，接入真实模型推理              | 已接入外部服务器远程 GPU 推理             | **达标** | 已实现基础 Top-1 输出                        |
| 模型输出   | 返回Top-1，真实的 Attention 矩阵与关键帧索引 | 已返回 logits/attention/关键帧索引        | **达标** | 继续优化注意力解释性与热点稳定性             |
| 专业可视化 | 真实时序概率曲线 (16帧动态概率)              | 已回传真实 `temporal_probs` 并渲染      | **达标** | 增加 Fast/Full 双模式降低延迟                |
| 专业可视化 | 真实注意力热力图 (Attention Map)             | 已使用 `feature_hook` 真实热图 + 热点框 | **达标** | 优化阈值与视觉样式，增强专家可读性           |
| 专业可视化 | 视频标注层叠加                               | 已支持服务端导出 + 本地端触发与下载       | **达标** | 继续优化长视频导出体验与可观测日志           |
| 工程能力   | 跨平台兼容性 (Win/Linux)                     | 已实现 SSH 隧道分布式计算架构             | **达标** | 固化 SSH 自动连接与心跳检查脚本              |
| 工程能力   | 500MB 上传支持                               | 当前基础上传可用                          | 部分达标       | 增加大文件切片上传与进度条展示               |
| 工程能力   | 推理耗时与 GPU 状态展示                      | 已展示总耗时/推理耗时与设备信息           | 部分达标       | 增加显存占用、GPU 利用率与温度字段并前端展示 |

## 本地端当前完成总结（2026-03-24）

1. **推理协议适配完成**

- 优先消费 `probs`，兼容回退 `logits`。
- 支持 `temporal_probs` 与 `temporal_frame_indices` 时间轴映射。
- 支持 `attention_source/attention_hook_mode/attention_normalization_mode` 信息透传。

2. **可视化链路升级完成**

- 热图来源由占位逻辑升级为远程 `attention_matrix`。
- 已接入 `attention_hotspots` 并在缩略图叠加热点框。
- 当 `temporal_source=static_fallback` 时，前端会显示回退提示。

3. **导出能力本地闭环完成**

- 本地后端已代理远程 `POST /render_expert_video`。
- 本地后端已代理远程 `GET /download/{filename}`。
- 前端已支持按钮触发导出并下载结果视频。

## 下一步工作（建议优先级）

### P0（优先做）

1. **大文件上传能力**

- 目标：支持 500MB 上传、断点续传、前端进度。
- 建议：改为分片上传与服务端流式写盘。

2. **导出任务异步化**

- 目标：避免长视频导出阻塞请求。
- 建议：任务队列 + 查询接口 + 结果回调。

### P1（增强可观测）

1. **GPU 运行状态字段**

- 在健康检查与推理返回中增加显存占用、利用率、温度。

2. **请求追踪 ID**

- 为每次推理与导出生成 `request_id`，本地与服务端日志可对齐追踪。

### P2（体验优化）

1. **双模式推理**

- `fast`：关闭时序额外前向，低延迟。
- `full`：开启时序与热图，完整分析。

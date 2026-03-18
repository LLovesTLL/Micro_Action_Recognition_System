# Micro Action Recognition System

## 项目概述

- 目标：构建前后端分离的微动作识别系统。
- 当前阶段：系统集成阶段（真实模型远程推理已打通）。
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
- **级联可视化链路**：远程返回推理结果，本地实时生成 **Grad-CAM 热力图** (4帧/组) 以及时序概率曲线。
- **调试监控**：增加控制台 DEBUG 模式，可实时查看远程返回的原始信息。

### 3) 前端页面（Vue + Vite）

- **动作映射支持**：支持 52 类动作的英文标签动态渲染。
- **链路反馈增强**：支持显示远程服务器状态（`Verified Inference by REMOTE Linux Server`）。

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
ssh -L 9000:localhost:9000 xcguo@omnisky
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

| 模块       | 验收项                                       | 当前状态                      | 结论           | 下一动作                                           |
| ---------- | -------------------------------------------- | ----------------------------- | -------------- | -------------------------------------------------- |
| 模型推理   | 替换 fallback，接入真实模型推理              | 已接入外部服务器远程 GPU 推理 | **达标** | 已实现基础 Top-1 输出                              |
| 模型输出   | 返回Top-1，真实的 Attention 矩阵与关键帧索引 | 目前仅返回 Top-1 类别         | 未达标         | **服务端**：修改并提取中间特征层返回数据     |
| 专业可视化 | 真实时序概率曲线 (16帧动态概率)              | 当前为本地根据 Top-1 模拟生成 | 未达标         | **服务端**：返回全量 52 类 Logits 概率数组   |
| 专业可视化 | 真实注意力热力图 (Attention Map)             | 当前为前端 Grad-CAM 占位图    | 未达标         | **服务端**：提取 Mamba 层/特征层注意力权重图 |
| 专业可视化 | 视频标注层叠加                               | 本地已支持热图叠加演示        | 部分达标       | **服务端**：生成带红框与置信度文本的标注视频 |
| 工程能力   | 跨平台兼容性 (Win/Linux)                     | 已实现 SSH 隧道分布式计算架构 | **达标** | 固化 SSH 自动连接与心跳检查脚本                    |
| 工程能力   | 500MB 上传支持                               | 当前基础上传可用              | 部分达标       | 增加大文件切片上传与进度条展示                     |
| 工程能力   | 推理耗时与 GPU 状态展示                      | 仅远程端日志可见              | 未达标         | 将耗时字段加入 JSON 返回值并在 UI 展示             |

## 下一步最小闭环（真实特征提取与回传）

### Step 1. 服务端推理增强 (Mamba Feature Data)

- **目标**：通过 **服务端(Linux)** 提取并返回完整的“推理报告”数据，不再局限于单一标签。
- **必做项**：
  - **[服务端]**：修改 `remote_inference_server.py`，获取模型 Forward Pass 输出的全量 52 类概率数组 (Logits)。
  - **[服务端]**：提取 Mamba 层/特征层的注意力权重矩阵 (Attention Maps) 或关键特征显著图。
- **完成判定**：本地后端接收到的 JSON 包含 `logits` (52维) 和 `attention_matrix` 字段。

### Step 2. 特征可视化闭环 (True Data Visualization)

- **目标**：前端曲线呈现随时间起伏的真实波动，热力图源自模型真实的关注热度。
- **必做项**：
  - **[本地端]**：更新 `model_service.py` 接收全量概率分布，前端时序图同步渲染服务端回传的真实 Logits 曲线。
  - **[本地端]**：将服务端回传的 `attention_matrix` 进行色标映射，作为真实热力图源替换目前的 Grad-CAM 占位图。

### Step 3. 专家视频渲染与下载 (Video Labeling)

- **目标**：在 **服务端(Linux)** 或本地端完成视频流与推理结果的物理合并（结果“烧录”）。
- **必做项**：
  - **[服务端/本地端]**：利用 OpenCV/FFmpeg 将类别标签、置信度数值和动作红框实时绘制进视频帧并合成视频文件。
  - **[本地端]**：Web 界面增加“导出专家视频”按钮，支持处理后的标注视频下载。

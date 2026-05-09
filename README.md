# Micro Action Recognition System

## 项目概述

- 目标：构建前后端分离的微动作识别系统。
- 当前阶段：系统联调与优化阶段（远程增强与本地适配已打通）。
- 当前模型状态：已接入 **Mamba** 真实视觉模型。
- 架构调整：采用 **分布式远程推理架构**（Local Windows GUI + Remote Linux GPU Server），通过 SSH 隧道实现跨平台高性能计算。

### 2026-04-24 增量更新（实时推理）

- 新增远程实时推理服务 `server/remote_realtime_inference_server.py`（默认端口 `9001`）。
- 本地后端新增 realtime 桥接接口：
  - `GET /api/v1/realtime/health`
  - `POST /api/v1/realtime/session/start`
  - `POST /api/v1/realtime/frame`
  - `POST /api/v1/realtime/session/stop`
- 前端主页面升级为双入口：`视频上传` / `实时推理`。
- 实时页面支持热点区域框叠加（当前来源：`motion_diff`），并显示热点分数。
- realtime 双模式当前语义：
  - `full`：每帧真实推理，准确性优先。
  - `fast`：跳帧推理 + 缓存复用，低延迟优先。
- 无动作拒识门控 + 短窗稳定器

### 2026-05-09 增量更新（PDF 报告导出）

- 新增一键导出推理报告（PDF）能力（前端触发，本地后端聚合生成）。
- 历史记录查看与新上传推理结果均会补齐 `source_filename`，保证报告命名一致。

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
- **报告导出能力接入**：新增“导出推理报告（PDF）”按钮，支持导出结果概览、Top-K、时序曲线与热力图。
- **原始文件名一致性**：报告导出优先透传 `source_filename`（上传原名），避免显示服务端中间文件名（如 `final.mp4`）。
- **双入口导航**：新增首页双入口，支持一键进入视频上传页和实时推理页。
- **实时可视化**：新增摄像头实时推理页面，支持 Top1/TopK/时延与热点框叠加展示。
- **历史推理记录**：识别完成后自动进入历史列表，支持查看详情、导出专家视频与下载；刷新页面保留，关闭页面后自动释放缓存。

### 4) 系统联调与工程化

- **SSH 隧道方案**：验证了 `9000 -> 9000` 端口转发的稳定性。
- **双端口隧道方案**：已验证 `9000 -> 9000` + `9001 -> 9001` 同时转发。
- **移除随机兜底**：关闭了 `fallback` 逻辑，确保 UI 显示结果均来自真实模型。

## 目录结构

- `backend/`：本机运行环境（Windows），处理业务逻辑与可视化
- `frontend/`：本机运行环境（Vue），处理交互展示
- `server/remote_inference_server.py`：部署在服务器（Linux）的推理引擎
- `server/remote_realtime_inference_server.py`：部署在服务器（Linux）的实时推理引擎
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
python remote_realtime_inference_server.py
```

建议分别在两个终端启动，分别监听 `9000` 和 `9001`。

### Step 2: 建立通信链路 (Windows Terminal)

```bash
ssh -N -L 9000:localhost:9000 -L 9001:localhost:9001 xxx@xxx.xxx.x.xxx
```

### Step 3: 手动启动本地应用 (推荐)

终端 1（后端）：

```bash
cd /d d:\Project\Micro_Action_Recognition_System
conda activate Micro_Action
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

终端 2（前端）：

```bash
cd /d d:\Project\Micro_Action_Recognition_System\frontend
(npm install)
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

### 5) 实时推理提示“远端实时服务不可达”

优先检查双端口隧道和健康检查：

```bash
http://127.0.0.1:9001/health
http://127.0.0.1:8000/api/v1/realtime/health
```

若 `9001` 不通，确认 SSH 使用了 `-L 9001:localhost:9001`。

### 6) 本地后端 `/api/v1/realtime/frame` 返回 422

说明：通常是服务端旧版本仍在运行。当前版本已按 `Form(...) + File(...)` 接收 multipart。

处理：重启本地 uvicorn 后再试。

### 7) 历史推理记录里的专家视频无法导出

历史导出依赖原始视频文件缓存。本版本使用浏览器 IndexedDB 做临时缓存：

- **刷新页面**：缓存仍在，可继续导出。
- **彻底关闭页面**：缓存会释放，需要重新上传视频后再导出。

## 达标检查表（系统集成与可视化）

| 模块       | 验收项                                       | 当前状态                                                             | 结论           | 下一动作                           |
| ---------- | -------------------------------------------- | -------------------------------------------------------------------- | -------------- | ---------------------------------- |
| 模型推理   | 替换 fallback，接入真实模型推理              | 已接入外部服务器远程 GPU 推理                                        | **达标** | 已实现基础 Top-1 输出              |
| 模型输出   | 返回Top-1，真实的 Attention 矩阵与关键帧索引 | 已返回 logits/attention/关键帧索引                                   | **达标** | 继续优化注意力解释性与热点稳定性   |
| 专业可视化 | 真实时序概率曲线 (16帧动态概率)              | 已回传真实 `temporal_probs` 并渲染                                 | **达标** | 增加 Fast/Full 双模式降低延迟      |
| 专业可视化 | 真实注意力热力图 (Attention Map)             | 已使用 `feature_hook` 真实热图 + 热点框                            | **达标** | 优化阈值与视觉样式，增强专家可读性 |
| 专业可视化 | 推理报告撰写（PDF 自动汇总）                 | 已支持一键导出 PDF，自动整合视频元信息、推理结果、时序曲线图、热力图 | **达标** | 持续优化报告版式与字段完整性       |
| 专业可视化 | 专家视频标注层叠加                           | 已支持服务端导出 + 本地端触发与下载                                  | **达标** | 继续优化长视频导出体验与可观测日志 |
| 专业可视化 | 专家视频显示微动作预测类别与置信度           | 已支持预测类别与置信度展示                                           | **达标** | 已实现相关功能                     |
| 工程能力   | 跨平台兼容性 (Win/Linux)                     | 已实现 SSH 隧道分布式计算架构                                        | **达标** | 固化 SSH 自动连接与心跳检查脚本    |
| 工程能力   | 500MB 上传支持                               | 已支持分片上传、断点续传、前端进度条展示                             | **达标** | 已实现相关功能                     |
| 工程能力   | 任务导出异步化                               | 已支持任务队列、状态查询、失败重试与下载                             | **达标** | 已实现相关功能                     |
| 工程能力   | 历史记录管理                                 | 已支持任务历史持久化、类别筛选、删除与清理                           | **达标** | 已实现相关功能                     |
| 工程能力   | 推理耗时展示                                 | 已展示总耗时/推理耗时与设备信息                                      | **达标** | 已经实现推理耗时展示               |
| 工程能力   | 实时推理链路（摄像头）                       | 已支持会话、帧推理、实时结果展示                                     | **达标** | 持续优化低延迟与鲁棒性             |
| 工程能力   | 实时热点区域框                               | 已支持 `motion_diff` 热点框叠加                                    | **达标** | 后续可升级为 attention 热点        |

## 完成工作总结

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
- 前端已支持一键导出推理报告（PDF）。

4. **P1 工程优化完成**

- 已完成 500MB 级别大文件分片上传、断点续传与前端上传进度显示。
- 已完成导出任务异步化：任务队列、状态查询、失败原因展示与页面端重试。
- 已完成导出任务历史管理：本地持久化保存、类别筛选、单条删除与清空历史。
- 已补充任务时间可读性：前端展示本地时间与任务耗时。

5. **实时推理能力新增**

- 已完成实时推理远端服务、后端桥接接口与前端实时页面闭环。
- 已完成 fast/full 双模式与低延迟优化（fast 跳帧推理 + 缓存复用）。
- 已完成实时热点框叠加（motion_diff）。
- 已完成无动作拒识门控 + 短窗稳定器，解决误识和单帧抖动问题。

6. **历史推理记录与缓存策略升级**

- 识别完成后自动写入历史记录，支持查看详情、导出专家视频与下载。
- 原始视频以浏览器 IndexedDB 临时缓存，刷新保留、关闭页面释放。
- 本地热力图等输出资源不再随清理逻辑删除，历史详情可稳定回看。

## 阶段性结论

- 当前项目核心目标已完成：真实远程模型推理链路、可视化链路、专家视频导出链路、工程化与可用性优化、实时推理均已闭环。
- 当前版本已满足本地演示与阶段验收需求，项目可阶段性告一段落。
- 后续若进入下一阶段，可按实际业务需求再规划新目标（例如更深层可解释性、自动化运维、性能压测与稳定性指标体系）。

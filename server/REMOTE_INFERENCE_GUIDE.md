# 远程推理架构部署指南 (Remote Inference Deployment Guide)

本指南面向当前项目的双链路架构：

- 链路 A：inference 视频上传识别（含专家视频导出）
- 链路 B：realtime 实时推理（摄像头逐帧）

目标是把两条链路拆开讲清楚，避免接口、参数和排障混用。

---

## 0. 架构总览

### 0.1 架构优势

- 本机零负载：本机无需安装 `mamba-ssm`, `causal-conv1d` 等重型依赖。
- 环境隔离：推理完全运行在 Linux 服务器模型环境（建议 `VideoMamba` conda 环境）。
- 安全传输：通过 SSH 隧道将服务端端口映射到本机，不暴露公网端口。

### 0.2 服务划分

- `remote_inference_server.py`：端口 `9000`，负责视频上传识别与导出。
- `remote_realtime_inference_server.py`：端口 `9001`，负责实时逐帧推理。
- 本地后端 `FastAPI`：端口 `8000`，负责桥接前端与远程服务。

---

## 1. 共用准备（两条链路都需要）

### 1.1 服务器端准备 (Linux)

1. 拷贝脚本到服务器：

- `remote_inference_server.py`
- `remote_realtime_inference_server.py`

2. 修改两个脚本开头路径：

```python
# 修改为服务器上项目绝对路径
PROJECT_ROOT = "/home/user/Project"

# 修改为服务器上 checkpoint 绝对路径
CHECKPOINT_PATH = "/home/user/Project/checkpoints/checkpoint-best.pth"
```

3. 安装依赖（在服务器模型环境）：

```bash
conda activate YourEnv
pip install torch torchvision opencv-python numpy
```

说明：当前脚本基于 `http.server`，不依赖 `fastapi/uvicorn`。

### 1.2 本机 SSH 隧道 (Windows)

保持一个终端常驻：

```powershell
ssh -N -L 9000:localhost:9000 -L 9001:localhost:9001 your_username@server_ip
```

### 1.3 本机应用启动

- 后端：`uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload`
- 前端：`cd frontend && npm run dev`

---

## 2. 链路 A：Inference 视频上传识别

本章节只讲上传视频后的一次性识别与导出，不包含摄像头实时推理。

### 2.1 服务端能力清单（9000）

- 真实模型推理（16 帧）
- Top-1 / Top-K / 52 类概率分布
- 真实时序概率 `temporal_probs`（16 x 52）
- 注意力矩阵 `attention_matrix` 与热点框 `attention_hotspots`
- 专家视频导出：热图 + 红框 + 类别 + 置信度烧录

### 2.2 关键配置项（remote_inference_server.py）

- `ENABLE_TEMPORAL_PROBS = True`

  - `True`：返回真实时序概率，信息更完整，耗时更高
  - `False`：关闭额外时序前向，速度更快
- `ATTENTION_NORMALIZE_MODE = "global"`

  - `global`：跨帧可比较，适合演示
  - `per_frame`：单帧内部对比更明显
- `HOTSPOT_THRESHOLD = 0.75`

  - 越高越聚焦，越低越敏感
- `RENDER_OUTPUT_DIR`, `RENDER_KEEP_MAX_FILES`

  - 导出目录与文件保留策略

### 2.3 接口说明（9000）

1. 健康检查：`GET /health`
2. 视频识别：`POST /predict`（`multipart/form-data`, 字段 `file`）
3. 专家导出：`POST /render_expert_video`（字段 `file`）
4. 文件下载：`GET /download/{filename}`

### 2.4 调用示例

```bash
curl -X POST "http://127.0.0.1:9000/predict" \
  -F "file=@/path/to/demo.mp4"
```

```bash
curl -X POST "http://127.0.0.1:9000/render_expert_video" \
  -F "file=@/path/to/demo.mp4"
```

```bash
curl -L "http://127.0.0.1:9000/download/expert_xxx.mp4" -o expert_result.mp4
```

### 2.5 上传识别链路验收标准

至少满足：

- `attention_source = feature_hook`
- `temporal_source = frame_repeat_forward`
- `temporal_probs_shape = [16, 52]`
- `attention_hotspots` 多数样本非空

### 2.6 上传识别常见问题

- 问题：大文件上传慢或超时

  - 原因：当前仍是基础 multipart 解析
  - 建议：后续升级分片上传与断点续传
- 问题：注意力图异常

  - 先检查：`feature_hook_layer` 是否有效
  - 回退行为：会退回 `input_fallback`

---

## 3. 链路 B：Realtime 实时推理

本章节只讲摄像头逐帧推理，不包含视频上传识别逻辑。

### 3.1 服务端能力清单（9001）

- 实时接口：`POST /realtime/predict-frame`
- 健康检查：`GET /health`
- fast/full 双模式
- 运动热点框 `hotspot`（`motion_diff`）
- 无动作拒识门控（防止静止时硬报 52 类）
- 短窗稳定器（多数投票，抑制抖动）

### 3.2 fast 与 full 的实现差异

- `full`：每次请求都真实前向，准确性与跟手性更高。
- `fast`：按 `FAST_INFER_EVERY_N` 做跳帧真实前向，其余帧复用缓存结果，延迟更低。

### 3.3 关键配置项（remote_realtime_inference_server.py）

- `FAST_INFER_EVERY_N`

  - fast 模式推理间隔，越大越省算力但越可能滞后
- `REJECT_TOP1_CONF_THRESH`

  - Top-1 置信度下限
- `REJECT_TOP1_TOP2_MARGIN_THRESH`

  - Top-1 与 Top-2 置信度间隔下限
- `REJECT_MOTION_SCORE_THRESH`

  - 运动分数下限（来自 `hotspot.score`）
- `REJECT_MIN_VOTES`

  - 拒识投票阈值（推荐 2）
- `SMOOTH_WINDOW`, `SMOOTH_MIN_COUNT`

  - 时序平滑窗口与稳定输出门槛

当满足拒识条件时：

- `top_class = no obvious action`
- `hotspot = null`

### 3.4 场景化推荐参数（三套）

#### A. 静坐监测（误报最低优先）

```python
FAST_INFER_EVERY_N = 2
REJECT_TOP1_CONF_THRESH = 0.70
REJECT_TOP1_TOP2_MARGIN_THRESH = 0.22
REJECT_MOTION_SCORE_THRESH = 0.16
REJECT_MIN_VOTES = 2
SMOOTH_WINDOW = 7
SMOOTH_MIN_COUNT = 4
```

#### B. 课堂监测（平衡推荐，默认基线）

```python
FAST_INFER_EVERY_N = 2
REJECT_TOP1_CONF_THRESH = 0.62
REJECT_TOP1_TOP2_MARGIN_THRESH = 0.16
REJECT_MOTION_SCORE_THRESH = 0.10
REJECT_MIN_VOTES = 2
SMOOTH_WINDOW = 5
SMOOTH_MIN_COUNT = 3
```

#### C. 交互演示（实时响应优先）

```python
FAST_INFER_EVERY_N = 1
REJECT_TOP1_CONF_THRESH = 0.52
REJECT_TOP1_TOP2_MARGIN_THRESH = 0.10
REJECT_MOTION_SCORE_THRESH = 0.05
REJECT_MIN_VOTES = 2
SMOOTH_WINDOW = 3
SMOOTH_MIN_COUNT = 2
```

调参顺序建议：

1. 先用课堂监测参数作为基线。
2. 误报多：先上调 `REJECT_MOTION_SCORE_THRESH`，再上调 `REJECT_TOP1_TOP2_MARGIN_THRESH`。
3. 漏检多：先下调 `REJECT_TOP1_CONF_THRESH`，再减小 `SMOOTH_WINDOW`。
4. 跟手不足：将 `FAST_INFER_EVERY_N` 调到 `1`，再微调拒识阈值。

### 3.5 接口说明（9001）

1. 健康检查：`GET /health`
2. 实时推理：`POST /realtime/predict-frame`

请求字段（multipart）：

- `session_id`
- `mode` (`fast` 或 `full`)
- `ts_client_ms`
- `frame`（jpg/png）

示例：

```bash
curl -X POST "http://127.0.0.1:9001/realtime/predict-frame" \
  -F "session_id=demo-session" \
  -F "mode=fast" \
  -F "ts_client_ms=$(date +%s%3N)" \
  -F "frame=@/path/to/frame.jpg"
```

### 3.6 实时链路验收标准

至少满足：

- `POST /realtime/predict-frame` 持续返回 200
- `timing.total_ms` 有效
- 热点框随动作更新
- 静止场景下可以稳定返回 `no obvious action`

### 3.7 实时链路常见问题

- 问题：持续 422

  - 检查本地后端 `/api/v1/realtime/frame` 是否使用 `Form(...) + File(...)`
- 问题：明明无动作仍在报类

  - 先切回“课堂监测”参数基线
  - 然后上调 `REJECT_MOTION_SCORE_THRESH`
- 问题：框停留在旧位置

  - 前端应在暂停或停止后隐藏 hotspot 渲染

---

## 4. 联合健康检查与排障

### 4.1 三个健康接口

- `http://localhost:9000/health`
- `http://localhost:9001/health`
- `http://127.0.0.1:8000/api/v1/realtime/health`

实时桥接健康要求：`remote_realtime.reachable = true`。

### 4.2 日志观察点

- 本地后端日志：`Inference completed by REMOTE Linux Server`
- 实时桥接日志：`POST /api/v1/realtime/frame 200`
- 远程服务日志：模型加载成功 + 请求持续到达

---

## 5. 最短启用清单

1. 服务器启动：

```bash
conda activate YourEnv
python remote_inference_server.py
python remote_realtime_inference_server.py
```

2. 本机建立隧道：

```powershell
ssh -N -L 9000:localhost:9000 -L 9001:localhost:9001 your_username@server_ip
```

3. 本机启动后端与前端。
4. 分链路验证：

- 上传识别链路：`/predict` 与 `/render_expert_video`
- 实时推理链路：前端实时页面 + `/realtime/predict-frame`

完成以上步骤，即可同时启用 inference 与 realtime 两条能力链路。

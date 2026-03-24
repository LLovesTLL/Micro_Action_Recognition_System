# 远程推理架构部署指南 (Remote Inference Deployment Guide)

本指南针对“本机 Windows 展示 + 远程 Linux 推理”的架构，利用 SSH 隧道实现跨平台高性能视频微动作识别。

## 架构优势
- **本机零负载**：无需在本机安装 `mamba-ssm`, `causal-conv1d` 等重型依赖，显存占用为 0。
- **环境隔离**：利用服务器已有的训练环境进行推理，避免全量文件迁移。
- **安全传输**：通过 SSH 隧道加密传输视频数据到服务器，无需暴露公网端口。

---

## 当前状态快照（2026-03-24）

服务器端 `remote_inference_server.py` 已完成以下能力：

1. **真实模型推理链路（已稳定）**
- 真实权重加载，支持 16 帧输入。
- 返回 Top-1 / Top-K、完整 52 维分布与原始 logits。

2. **真实特征注意力（已替换兜底）**
- 特征钩子模式已稳定命中（当前常见：`named_candidate`）。
- 注意力来源已可稳定达到 `feature_hook`。
- 支持 token 序列特征（含 cls token）到 `T x 14 x 14` 的映射。

3. **真实时序概率（已上线）**
- 返回 `temporal_probs`（`16 x 52`）。
- 返回时序来源与采样索引，便于前端按时间轴对齐。

4. **可读性增强（已上线）**
- 支持全局归一化热图（默认 `global`）。
- 返回每帧热点框 `attention_hotspots`（可直接前端画红框）。

5. **专家视频导出（已上线）**
- `POST /render_expert_video`：服务端推理 + 视频烧录。
- `GET /download/{filename}`：下载导出 mp4。
- 导出视频包含类别、置信度、热图叠加、热点框。

---

## 一、服务器端准备 (Linux)

### 1. 部署推理脚本
将项目根目录下的 `remote_inference_server.py` 拷贝至服务器任意目录。

### 2. 配置路径
编辑 `remote_inference_server.py` 开头的配置部分：
```python
# 修改为服务器上 VideoMambaPro 源码所在绝对路径
sys.path.append("/home/user/VideoMambaPro") 

# 修改为服务器上已训练权重的绝对路径
CHECKPOINT_PATH = "/home/user/VideoMambaPro/checkpoints/checkpoint-best.pth"
```

### 3. 安装后端依赖 (在服务器模型环境中)
```bash
conda activate VideoMamba

# 保留当前 http.server 传输方式，不需要安装 fastapi/uvicorn
# 以下是 remote_inference_server.py 实际依赖（标准库不需要安装）
pip install torch torchvision opencv-python numpy

# 可选：如果需要在返回中扩展 GPU 更详细监控
pip install nvidia-ml-py
```

> 说明：你当前环境已包含上述核心包，通常无需重复安装。

### 4. 启动服务
```bash
python remote_inference_server.py
```
*服务默认运行在服务器的 `9000` 端口。*

### 4.1 启用配置（建议）

在 `remote_inference_server.py` 顶部可按需调整：

- `ENABLE_TEMPORAL_PROBS = True`
	- `True`：返回真实时序概率（更真实，耗时更高）
	- `False`：关闭时序额外前向（更快）

- `ATTENTION_NORMALIZE_MODE = "global"`
	- `global`：帧间强度可比较（推荐演示）
	- `per_frame`：每帧独立归一化（推荐看单帧内部热点）

- `HOTSPOT_THRESHOLD = 0.75`
	- 越高：红框更聚焦
	- 越低：红框更大、更敏感

- `RENDER_OUTPUT_DIR = "/tmp/micro_action_renders"`
	- 导出视频保存目录

- `RENDER_KEEP_MAX_FILES = 40`
	- 导出文件保留上限，超出后自动清理旧文件

### 5. 远程接口返回字段（升级后）

`POST /predict` 在原有 `prediction/confidence/label_id` 基础上，新增（或增强）字段：
- `logits`: 52 维概率数组（softmax 后，向后兼容字段）
- `logits_raw`: 52 维原始 logits（模型线性头直接输出）
- `probs`: 52 维概率数组（与 `logits` 一致，用于新版本语义清晰化）
- `num_classes`: 类别总数（当前固定 52）
- `attention_matrix`: `16 x 14 x 14` 注意力矩阵（优先特征层，失败则输入兜底）
- `attention_shape`: 注意力尺寸元信息
- `attention_source`: `feature_hook` 或 `input_fallback`
- `attention_hook_layer`: 当前挂钩层名称
- `attention_hook_mode`: 挂钩选择模式（`named_candidate` / `suffix_candidate` / `keyword_fallback`）
- `attention_normalization_mode`: 注意力归一化模式（`global` 或 `per_frame`）
- `attention_hotspots`: 每帧热点框（归一化坐标）
- `attention_hotspot_threshold`: 热点阈值（当前默认 `0.75`）
- `topk`: Top-5 结果列表
- `temporal_probs`: 真实时序概率，形状 `16 x 52`（逐帧构造 clip 的前向结果）
- `temporal_probs_shape`: 时序概率尺寸元信息
- `temporal_source`: `frame_repeat_forward`（失败时回退 `static_fallback`）
- `temporal_frame_indices`: 16 帧对应原视频采样索引
- `num_total_frames`: 原视频总帧数
- `video_fps`: 原视频帧率
- `video_duration_sec`: 原视频时长（秒）
- `preprocess_time_ms`: 预处理耗时（毫秒）
- `inference_time_ms`: 推理耗时（毫秒）
- `temporal_inference_time_ms`: 时序概率计算耗时（毫秒）
- `postprocess_time_ms`: 后处理耗时（毫秒）
- `total_time_ms`: 端到端总耗时（毫秒）
- `device`: 推理设备

说明：
- 为兼容旧版本地端，`logits` 仍保留为概率数组；推荐新对接逻辑优先读取 `probs` 与 `logits_raw`。
- 当前 `attention_matrix` 为特征层显著图近似；若特征钩子失败，会自动回退为输入能量图（`input_fallback`）。
- `temporal_probs` 由服务端真实前向生成，可直接驱动前端“时序概率曲线”；若发生异常，会回退为静态分布并在 `temporal_source` 中标记。

### 5.1 快速验收标准（服务端）

至少满足以下字段判定服务端增强成功：

- `attention_source = feature_hook`
- `attention_hook_mode in {named_candidate, suffix_candidate, keyword_fallback}`
- `temporal_source = frame_repeat_forward`
- `temporal_probs_shape = [16, 52]`
- `attention_normalization_mode` 与配置一致
- `attention_hotspots` 非空（多数样本）

### 6. 专家视频导出接口（新增）

- `POST /render_expert_video`
- 请求方式：`multipart/form-data`，字段与 `/predict` 一致（`file`）
- 返回字段：
	- `render_id`: 导出任务唯一标识
	- `render_filename`: 生成的 mp4 文件名
	- `download_url`: 下载路径（示例：`/download/expert_xxx.mp4`）
	- `render_meta`: 导出视频元信息（帧数/FPS/分辨率/时长）
	- `inference`: 完整推理结果（与 `/predict` 返回结构一致）

- `GET /download/{filename}`
	- 用于下载导出的专家标注视频（`video/mp4`）

说明：
- 导出视频会叠加类别、置信度、注意力热图和热点框（红框）。
- 服务端默认保留最近一批导出文件，旧文件会自动清理。

### 6.1 调用示例

推理：

```bash
curl -X POST "http://127.0.0.1:9000/predict" \
	-F "file=@/path/to/demo.mp4"
```

导出：

```bash
curl -X POST "http://127.0.0.1:9000/render_expert_video" \
	-F "file=@/path/to/demo.mp4"
```

下载（把返回里的 `download_url` 拼到服务地址）：

```bash
curl -L "http://127.0.0.1:9000/download/expert_xxx.mp4" -o expert_result.mp4
```

---

## 二、本机端准备 (Windows)

### 1. 建立 SSH 隧道
由于服务器 9000 端口通常不对外开放，需在本机执行以下命令（不要关闭）：
```powershell
# 将服务器的 9000 映射到本机的 9000
ssh -L 9000:localhost:9000 your_username@server_ip
```

### 2. 移除冗余文件
根据新架构，本机已不再需要本地推理代码，可安全删除：
- `backend/app/ml/` 文件夹（如果已创建）
- `backend/requirements.real-infer.txt`（如果已创建）

### 3. 运行系统
正常启动本地后端和前端：
- **后端**: `python run_backend.bat` (或 `uvicorn backend.app.main:app`)
- **前端**: `npm run dev`

---

## 三、故障排查与状态确认

### 1. 健康检查
在本机浏览器访问：`http://localhost:9000/health`
- 预期返回示例：
```json
{
	"status": "remote_server_alive",
	"device": "cuda",
	"model_loaded": true,
	"gpu_available": true,
	"num_frames": 16,
	"feature_hook_layer": "..."
}
```

建议额外关注：
- `feature_hook_mode`
- `temporal_probs_enabled`
- `attention_normalization_mode`

### 2. 日志监控
- **本地后端日志**：若看到 `Inference completed by REMOTE Linux Server` 表示链路通畅。
- **远程服务器日志**：若看到上传请求并打印 `Loading Model...` 表示推理正在执行。

---

## 四、目标达成映射（对照 README 达标检查表）

按当前联调结果，服务器端状态可归纳为：

1. **模型推理**：达标
- 真实模型、真实返回、Top-1/Top-K 可用。

2. **模型输出（logits + attention）**：达标
- 已回传 52 维分布、原始 logits、注意力矩阵。

3. **真实时序曲线数据**：达标
- 已回传 `temporal_probs` 与采样索引。

4. **真实注意力热图**：达标
- 已回传 `feature_hook` 来源注意力，并提供热点框。

5. **视频标注层叠加**：达标（服务器端）
- 已具备导出接口与下载接口。

6. **推理耗时展示**：达标（服务器端）
- 已返回预处理/推理/时序/后处理/总耗时。

7. **500MB 上传支持**：未达标（待优化）
- 当前仍是基础 multipart 解析，尚未切片/断点续传。

---

## 五、下一步工作（建议优先级）

### P0（优先做）

1. **大文件上传能力**
- 目标：支持 500MB 上传、断点续传、前端进度。
- 建议：改为分片上传与服务端流式写盘。

2. **导出任务异步化**
- 目标：避免长视频导出阻塞请求。
- 建议：任务队列 + 查询接口 + 结果回调。

### P1（增强可观测）

1. **GPU 运行状态字段**
- 建议在健康检查与推理返回中增加：显存占用、利用率、温度。

2. **请求追踪 ID**
- 为每次推理生成 `request_id`，本地端日志与服务端日志可对齐追踪。

### P2（体验优化）

1. **双模式推理**
- `fast`：关闭时序前向，低延迟。
- `full`：开启时序与热图，完整分析。

---

## 六、启用清单（最短路径）

1. 服务器启动：

```bash
conda activate VideoMamba
python remote_inference_server.py
```

2. 本机建立隧道：

```powershell
ssh -L 9000:localhost:9000 your_username@server_ip
```

3. 健康检查：
- `http://localhost:9000/health`

4. 联调检查：
- 调 `POST /predict`，确认 `attention_source=feature_hook`。
- 调 `POST /render_expert_video`，确认可下载导出视频。

完成上述 4 步即可启用当前版本全部服务端能力。

# Micro Action Recognition System 项目代码详解报告

## 1. 文档目标

本文档用于帮助后续开发者快速理解本项目的整体结构、核心代码路径、请求链路、关键数据结构和扩展点。

适用读者：

- 新加入项目的研发同学
- 需要定位线上联调问题的同学
- 需要在现有基础上继续优化模型服务与可视化能力的同学

---

## 2. 项目全景与设计思想

### 2.1 架构定位

项目采用分布式远程推理架构：

- 本机 Windows 负责交互与业务编排
- 远程 Linux + GPU 负责模型推理与专家视频渲染
- 两端通过 HTTP 接口通信，通常经 SSH 隧道进行本地端口映射

核心原则：

1. 本机轻量化：不在 Windows 上安装难编译的深度学习依赖
2. 远程计算集中化：推理与重处理在 Linux 端统一完成
3. 接口契约稳定：远程字段不断增强但保留兼容字段

### 2.2 目录职责

- backend：本地 FastAPI 服务，负责上传校验、远程调用、结果规范化、静态资源与下载代理
- frontend：Vue 页面，负责上传、结果可视化、导出触发
- remote_inference_server.py：远程 Linux 侧推理服务，负责真实模型推理、注意力提取、时序概率、视频导出
- remote_realtime_inference_server.py：远程 Linux 侧实时推理服务，负责摄像头帧实时识别与热点框生成
- REMOTE_INFERENCE_GUIDE.md：远程部署与联调手册
- README.md：项目总体状态与开发入口

---

## 3. 端到端请求链路

## 3.1 推理链路（预测）

1. 前端创建上传会话，调用本地接口 POST /api/v1/upload-sessions
2. 前端按分片上传视频，调用 PUT /api/v1/upload-sessions/{session_id}/chunks/{chunk_index}
3. 前端调用 POST /api/v1/upload-sessions/{session_id}/infer 触发推理
4. 本地后端在会话内合并文件并调用远程接口 POST /predict
5. 远程服务完成：

- 视频预处理
- 模型前向
- attention_matrix 生成
- temporal_probs 生成
- topk/耗时/元信息组织

6. 本地后端将远程结果转成本地统一响应结构
7. 前端渲染：

- Top1/TopK
- 时序曲线
- 热图缩略图与热点框
- 性能与来源信息
- 推理结果进入“历史推理记录”（前端临时缓存）

## 3.1.1 情绪分析链路（Gemini）

1. 前端创建上传会话并完成分片上传（同推理链路）
2. 前端调用 POST /api/v1/upload-sessions/{session_id}/analyze
3. 本地后端合并文件，执行动作识别得到 Top-1
4. 本地后端创建情绪分析任务（Gemini Worker）并返回 emotion_job_id
5. 前端轮询 GET /api/v1/emotion-jobs/{job_id} 获取情绪分析结果
6. 前端在结果页展示情绪分析，并将其写入导出报告

## 3.2 导出链路（专家视频）

1. 前端创建上传会话并完成分片上传（同推理链路）
2. 前端调用 POST /api/v1/upload-sessions/{session_id}/render-expert-async 创建异步导出任务
3. 后端将任务放入导出队列，返回 job_id
4. 前端轮询 GET /api/v1/render-jobs/{job_id} 查询任务状态
5. 任务成功后返回 result.local_download_url，前端触发下载
6. 导出任务同时进入任务历史，可在页面按类别筛选、删除与清理

## 3.3. 导出链路（PDF 报告）

1. 前端结果页点击“导出推理报告（PDF）”。
2. `ResultDashboard` 采集当前时序曲线图与热力图路径，并通过 `export-report` 事件上抛。
3. `UploadWorkspace` 组装导出 payload，使用上抛的 `source_filename` 作为报告视频名来源。
4. 前端调用本地接口 `POST /api/v1/export-report`。
5. 本地后端聚合推理结果、情绪分析与可视化资源并生成 PDF，返回文件流供前端下载。

## 3.4 实时推理链路

1. 前端主页面选择“实时推理”，进入实时页。
2. 前端调用 POST /api/v1/realtime/session/start 创建会话，获取 session_id。
3. 前端周期性抓取摄像头帧并调用 POST /api/v1/realtime/frame（multipart）。
4. 本地后端将帧转发到远程 POST /realtime/predict-frame。
5. 远程实时服务完成：

- 16 帧滑窗构造
- 模型前向（fast/full）
- 运动差分热点框（hotspot）
- timing 与 topk 组织

6. 本地后端透传并规范化响应。
7. 前端实时渲染：

- Top1/TopK
- 时延
- 热点框叠加到摄像头画面
- 会话状态与成功率

---

## 4. 本地后端代码解读

## 4.1 应用入口

文件：backend/app/main.py

职责：

- 创建 FastAPI 应用
- 配置 CORS
- 暴露健康检查 /health
- 挂载业务路由 /api/v1

设计点：

- 健康检查只代表本地后端存活，不代表远程模型服务可用
- 远程连通性由 ModelService 独立检查

## 4.2 配置管理

文件：backend/app/core/config.py

职责：

- 集中管理路径、上传上限、CORS
- 启动时确保 uploads 与 outputs 目录存在

可优化项：

- class_names 当前保留旧占位字段，实际分类映射已经由 ModelService 内部 52 类维护
- 建议后续统一到单一配置源，避免重复定义

## 4.3 路由层

文件：backend/app/api/routes.py

关键接口：

1. POST /upload-sessions

- 创建分片上传会话
- 返回 session_id、分片参数与已上传状态

2. PUT /upload-sessions/{session_id}/chunks/{chunk_index}

- 上传单个分片
- 支持断点续传（已上传分片可跳过）

3. POST /upload-sessions/{session_id}/infer

- 合并会话分片文件
- 调用 run_inference_pipeline

3.1 POST /upload-sessions/{session_id}/analyze

- 合并会话分片文件
- 先执行动作识别 Top-1
- 创建 Gemini 情绪分析任务并返回 emotion_job_id

4. POST /upload-sessions/{session_id}/render-expert-async

- 基于会话文件创建异步导出任务
- 返回 job_id

5. GET /render-jobs/{job_id}

- 查询导出任务实时状态（queued/running/success/error）

6. GET /render-jobs

- 查询任务历史列表
- 支持 status 与 class_label 筛选

7. DELETE /render-jobs/{job_id}

- 删除单条任务（支持 force）

8. DELETE /render-jobs

- 清空历史任务（支持按状态筛选、force 控制）

9. POST /infer（兼容直传）

- 直传模式推理入口（保留）

10. POST /render-expert（兼容直传）

- 直传模式导出入口（保留）

11. GET /remote-download/{filename}

- 本地代理远程下载流
- 用 StreamingResponse 分块透传

12. GET /assets/{filename}

- 返回本地生成的热图与帧图资源

13. GET /realtime/health

- 返回本地 realtime 桥接状态与远程 realtime 可达性

14. POST /realtime/session/start

- 创建实时会话，返回 session_id

15. POST /realtime/frame

- 接收单帧图片并转发远程实时推理，返回实时识别结果

16. POST /realtime/session/stop

- 停止并清理实时会话

17. GET /emotion-jobs/{job_id}

- 查询情绪分析任务状态与结果

设计点：

- 分片会话与直传模式并存，兼容老调用链
- 上传采用流式写盘，避免一次性读入大文件内存
- 导出任务具备历史管理能力（查询/筛选/删除/清空）
- 下载代理让前端只访问本地域名，减少跨域与认证复杂度

## 4.4 远程调用层

文件：backend/app/services/model_service.py

职责：

- 管理远程健康检查
- 统一远程 POST 上传逻辑
- 提供预测调用与导出调用
- 提供远程下载流请求

核心方法：

- predict_remote
- render_expert_video_remote
- stream_remote_download
- _post_video_to_remote
- predict_realtime_frame_remote
- check_realtime_health

设计点：

- 通过 remote_base_url 统一拼接远程端点
- 错误输出标准化为 error 字段，便于上层处理

## 4.5 推理编排层

文件：backend/app/services/pipeline_service.py

职责：

- 将远程原始结果转为前端友好的结构
- 对 temporal_probs 做时间轴对齐
- 基于 attention_matrix 生成本地可视化资产
- 透传关键诊断字段

关键逻辑：

1. 类别分布兼容

- 优先读取 probs
- 回退 logits

2. 时序数据对齐

- 若远程返回 temporal_probs + temporal_frame_indices + video_fps
- 则用 index/fps 计算真实时间轴
- 否则退化为均匀时间分布

3. 热图生成

- 从 attention_matrix 抽样 4 帧生成热图
- 叠加热点框（hotspot）信息
- 输出可访问路径 /api/v1/assets/xxx

4. 结构透传

- attention_source
- attention_hook_mode
- attention_normalization_mode
- attention_hotspots
- temporal_source
- timing 字段

设计点：

- 本地层不做模型计算，主要做结果组织与可视化资产准备
- 兼容字段设计使得远程升级时本地不易断裂

## 4.6 上传会话服务

文件：backend/app/services/upload_session_service.py

职责：

- 管理上传会话元数据
- 接收分片、记录已上传分片
- 合并分片为完整视频
- 支持断点续传查询

关键能力：

- create_session
- write_chunk
- get_status
- assemble_file
- delete_session

设计点：

- 会话目录与分片目录隔离，结构清晰
- 合并后做总大小校验，避免文件损坏进入推理链路

## 4.7 导出任务服务

文件：backend/app/services/export_job_service.py

职责：

- 维护异步导出任务队列
- 跟踪任务状态与错误信息
- 保存任务历史（本地持久化）

关键能力：

- create_job / get_job / list_jobs
- delete_job / clear_jobs

设计点：

- 采用线程池执行导出任务，避免阻塞主请求
- 任务历史持久化到 backend/storage/outputs/render_jobs_history.json
- 记录 class_label，便于页面按类别检索历史

## 4.8 可视化服务层

文件：backend/app/services/visualization_service.py

职责：

- 保存原帧
- 生成 attention 叠加图
- 叠加热点框

说明：

- create_attention_overlay 支持传入 hotspot 坐标并绘制红框
- 若 attention 渲染失败，pipeline 会回退到基础热图逻辑

## 4.9 数据模型

文件：backend/app/schemas/inference.py

职责：

- 统一定义接口输出结构
- 约束前后端契约

核心模型：

- InferenceResponse
- AttentionHotspot
- HeatmapFrame
- RenderExpertResponse
- RealtimeFrameResponse
- RealtimeHotspot

设计点：

- 既有业务字段，也有可观测字段（source/mode/time 等）
- 导出接口返回中保留 inference 原始结构，利于调试

---

## 5. 前端代码解读

## 5.1 入口与页面容器

文件：frontend/src/main.js
文件：frontend/src/App.vue

职责：

- 挂载根组件
- 管理首页双入口状态：视频上传 / 实时推理
- 管理上传工作区与实时工作区视图切换

设计点：

- 原有上传能力完整保留
- 新增实时页面，不影响原有上传识别与导出链路

## 5.2 上传组件

文件：frontend/src/components/UploadPanel.vue

职责：

- 文件选择与拖拽
- 提交选择文件
- 上传进度展示（分片上传过程）

说明：

- 组件保持无业务耦合，只负责拿到文件并 emit
- 当用户查看历史推理结果时，上传模块不显示当前视频预览

## 5.3 结果看板

文件：frontend/src/components/ResultDashboard.vue

职责：

- 渲染 Top1/TopK
- 渲染时序曲线
- 渲染热图缩略图
- 渲染热点红框
- 显示 attention/temporal 来源与性能信息
- 提供导出按钮

关键点：

1. 曲线横轴

- 使用时间戳 t，而不是点位索引，保证与原视频时间语义一致

2. 回退提示

- 当 temporal_source=static_fallback 时展示风险提示

3. 热点框渲染

- 读取 HeatmapFrame.hotspot 的归一化坐标
- 在缩略图上绝对定位绘制红框

## 5.4 API 调用封装

文件：frontend/src/services/api.js

职责：

- 上传会话管理：创建、分片上传、会话状态查询
- 推理触发：inferVideoChunked
- 异步导出：createRenderExpertJob + pollRenderJobUntilDone
- 任务管理：listRenderJobs / deleteRenderJob / clearRenderJobs
- 实时推理：getRealtimeHealth / startRealtimeSession / sendRealtimeFrame / stopRealtimeSession
- 历史推理记录与导出逻辑由前端 UploadWorkspace 本地维护

## 5.5 实时推理页面

文件：frontend/src/views/RealtimeWorkspace.vue

职责：

- 管理摄像头权限与采样
- 管理实时会话生命周期
- 展示 Top1/TopK/时延
- 在视频上叠加热点框

关键点：

1. 推理模式

- fast：跳帧真实推理 + 结果缓存，低延迟
- full：每帧真实推理，准确性优先

2. 热点框

- 当前读取后端返回 RealtimeHotspot
- 坐标为归一化比例，前端按百分比绝对定位绘制

## 5.6 历史推理记录

位置：frontend/src/views/UploadWorkspace.vue

职责：

- 识别完成后写入历史记录（视频名/类别/开始结束时间/推理结果）
- 支持查看详情、导出专家视频、下载导出结果
- 刷新页面保留缓存；关闭页面后释放缓存

实现要点：

- 记录列表存 sessionStorage
- 原始视频文件存 IndexedDB，按会话 token 进行隔离
- 若记录没有导出结果，点击“下载”会先触发导出，再下载
- 查看历史详情时会补齐 `source_filename`，用于报告导出时保持原始文件名一致

---

## 6. 远程服务 remote_inference_server.py 详解（重点）

本文件是系统核心计算引擎，承担推理、时序分析、注意力解释与视频导出。

## 6.1 配置区

主要参数：

- CHECKPOINT_PATH：模型权重路径
- DEVICE：cuda/cpu
- NUM_FRAMES：采样帧数，当前 16
- ATTENTION_GRID：注意力网格，当前 14
- ENABLE_TEMPORAL_PROBS：是否启用真实时序前向
- ATTENTION_NORMALIZE_MODE：global 或 per_frame
- HOTSPOT_THRESHOLD：热点阈值
- RENDER_OUTPUT_DIR：导出目录

建议：

- 演示场景推荐 ATTENTION_NORMALIZE_MODE=global
- 低延迟场景可临时关闭 ENABLE_TEMPORAL_PROBS

## 6.2 模型加载与特征钩子

流程：

1. 导入模型构建函数
2. 创建模型并加载 checkpoint
3. 调用 _register_feature_hook 挂接特征层

钩子策略分三层：

- 显式候选层名匹配
- 后缀匹配
- 关键词兜底

目标：

- 尽量稳定命中特征层，提高 attention_source=feature_hook 的概率

## 6.3 视频预处理

函数：preprocess_video

输出：

- 标准化后输入张量 [1, C, T, H, W]
- sampled_indices
- fps
- duration_sec
- num_total_frames

实现点：

- 均匀采样 NUM_FRAMES
- 短视频补帧
- RGB 转换与 ImageNet 归一化

## 6.4 推理与结果组织

公共函数：_run_inference_from_video_path

包含：

- 前向 logits/probs/topk
- attention_matrix 生成
- attention_hotspots 提取
- temporal_probs 生成（逐帧重复 clip 前向）
- timing 拆分统计

兼容性设计：

- 保留 logits 概率字段用于老版本兼容
- 新版本推荐使用 probs 与 logits_raw

## 6.5 注意力与热点框

关键函数：

- _to_attention_from_feature
- _to_attention_from_input
- _extract_attention_hotspots

说明：

- 优先基于特征层输出生成注意力
- 失败时回退输入能量图
- 热点框输出归一化坐标，前端可直接渲染

## 6.6 专家视频导出

关键函数：

- _render_expert_video

叠加内容：

- 注意力热图
- 热点红框
- 类别与置信度文字

接口：

- POST /render_expert_video
- GET /download/{filename}

说明：

- 导出文件数量受 RENDER_KEEP_MAX_FILES 控制
- 服务会清理旧文件，避免目录无限增长

## 6.7 路由处理器

类：VideoMambaInferenceHandler

路由：

- GET /health
- POST /predict
- POST /render_expert_video
- GET /download/{filename}

实现特征：

- 使用 http.server + cgi.parse_multipart
- 无 FastAPI 依赖，部署简单

## 6.8 远程实时服务 remote_realtime_inference_server.py

本文件负责摄像头实时推理与低延迟优化。

关键能力：

- POST /realtime/predict-frame
- GET /health
- 会话缓存与 TTL 清理
- fast/full 双模式
- motion_diff 热点框输出
- 无动作拒识门控 + 短窗稳定器

低延迟策略：

- GPU AMP 半精度推理
- 启动预热
- fast 模式跳帧推理 + 缓存复用

---

## 7. 数据契约要点（学习与联调重点）

预测核心字段：

- prediction / confidence / label_id
- probs / logits_raw / topk
- attention_matrix / attention_hotspots
- temporal_probs / temporal_frame_indices / temporal_source
- preprocess_time_ms / inference_time_ms / total_time_ms

导出核心字段：

- render_filename
- download_url（远程）
- local_download_url（本地代理）
- render_meta
- inference（完整推理结果）
- source_filename（报告导出用原始文件名）

实时核心字段：

- session_id / frame_id / mode
- top_class / top_confidence / topk
- hotspot（x1,y1,x2,y2,score,source）
- timing（queue_ms, remote_infer_ms, roundtrip_ms, total_ms）
- warming_up / source

---

## 8. 常见排障路径

1. 前端报 Network Error

- 检查本地后端 health
- 检查 SSH 隧道是否保持
- 检查远程 /health

2. temporal_source=static_fallback

- 说明时序额外前向失败
- 优先看远程日志中的 temporal_probs 异常

3. attention_source=input_fallback

- 说明特征钩子失效
- 优先检查 FEATURE_HOOK_CANDIDATES 与模型结构是否匹配

4. 导出失败

- 先看任务面板状态与 error 字段
- 检查 /api/v1/render-jobs/{job_id} 返回状态是否为 error
- 检查远程 render_expert_video 接口响应
- 检查本地 /api/v1/remote-download 代理是否可访问
- 检查远程导出目录写权限

5. 上传中断或刷新页面后继续失败

- 检查浏览器 localStorage 的上传会话是否仍存在
- 检查 /api/v1/upload-sessions/{session_id} 是否返回有效 uploaded_chunks
- 若会话已失效，前端会自动创建新会话重新上传

6. 实时推理 422

- 通常是后端未更新到 Form+File 的参数签名
- 重启 uvicorn 并确认 `/api/v1/realtime/frame` 使用 multipart 提交

7. 实时推理不可达

- 检查 9001 远程服务是否启动
- 检查 SSH 是否映射 9001
- 检查 /api/v1/realtime/health 的 remote_realtime.reachable

8. 导出的 PDF 视频名显示为 `final.mp4`

- 检查前端导出 payload 是否携带 `source_filename`。
- 检查 `UploadWorkspace` 在推理成功与历史详情场景是否补齐 `source_filename`。
- 若历史记录产生于旧版本（无 `source_filename`），建议重新推理一次生成新记录。

---

## 9. 推荐阅读顺序

建议按以下顺序阅读代码：

1. backend/app/main.py
2. backend/app/api/routes.py
3. backend/app/services/model_service.py
4. backend/app/services/pipeline_service.py
5. backend/app/schemas/inference.py
6. frontend/src/App.vue
7. frontend/src/components/ResultDashboard.vue
8. server/remote_inference_server.py
9. server/remote_realtime_inference_server.py

这样可以先理解本地业务边界，再深入远程重计算细节。

---

## 10. 结语

当前项目已经从“可跑通演示”升级到“可解释、可导出、可联调、可管理历史、可实时”的工程状态。
本地端已完成分片上传、异步导出、任务历史管理、实时推理等关键优化，具备阶段性交付条件。
新增 Gemini 情绪分析能力后，系统已形成“动作识别 + 情绪分析”的双结果输出链路，满足演示与报告场景需求。
新增 Gemini 情绪分析能力后，系统已形成“动作识别 + 情绪分析”的双结果输出链路，满足演示与报告场景需求。

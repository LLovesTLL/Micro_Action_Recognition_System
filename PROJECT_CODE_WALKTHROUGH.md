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
- REMOTE_INFERENCE_GUIDE.md：远程部署与联调手册
- README.md：项目总体状态与开发入口

---

## 3. 端到端请求链路

## 3.1 推理链路（预测）

1. 前端上传视频，调用本地接口 POST /api/v1/infer
2. 本地后端保存上传文件至 backend/storage/uploads
3. 本地后端调用远程接口 POST /predict
4. 远程服务完成：
- 视频预处理
- 模型前向
- attention_matrix 生成
- temporal_probs 生成
- topk/耗时/元信息组织
5. 本地后端将远程结果转成本地统一响应结构
6. 前端渲染：
- Top1/TopK
- 时序曲线
- 热图缩略图与热点框
- 性能与来源信息

## 3.2 导出链路（专家视频）

1. 前端点击导出按钮，调用本地接口 POST /api/v1/render-expert
2. 本地后端调用远程接口 POST /render_expert_video
3. 远程侧执行推理并烧录视频，返回 render_filename 与 download_url
4. 本地后端将远程下载路径包装为本地代理路径 local_download_url
5. 前端打开 local_download_url，由本地后端转发远程视频流下载

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
1. POST /infer
- 校验扩展名与空文件
- 校验大小上限
- 写入临时上传文件
- 调用 run_inference_pipeline

2. POST /render-expert
- 与 /infer 同样的上传校验流程
- 调用 model_service.render_expert_video_remote
- 注入 local_download_url 给前端

3. GET /remote-download/{filename}
- 本地代理远程下载流
- 用 StreamingResponse 分块透传

4. GET /assets/{filename}
- 返回本地生成的热图与帧图资源

设计点：
- /render-expert 与 /infer 都复用了统一上传校验逻辑模式
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

## 4.6 可视化服务层

文件：backend/app/services/visualization_service.py

职责：
- 保存原帧
- 生成 attention 叠加图
- 叠加热点框

说明：
- create_attention_overlay 支持传入 hotspot 坐标并绘制红框
- 若 attention 渲染失败，pipeline 会回退到基础热图逻辑

## 4.7 数据模型

文件：backend/app/schemas/inference.py

职责：
- 统一定义接口输出结构
- 约束前后端契约

核心模型：
- InferenceResponse
- AttentionHotspot
- HeatmapFrame
- RenderExpertResponse

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
- 管理全局页面状态：loading、error、result、exporting
- 分发两个核心动作：
  - onSubmit：触发推理
  - onExportExpertVideo：触发导出并下载

设计点：
- 导出依赖最近一次上传文件，若文件缺失会阻止导出并给提示

## 5.2 上传组件

文件：frontend/src/components/UploadPanel.vue

职责：
- 文件选择与拖拽
- 提交选择文件

说明：
- 组件保持无业务耦合，只负责拿到文件并 emit

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
- inferVideo 调用 /api/v1/infer
- renderExpertVideo 调用 /api/v1/render-expert

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
- 检查远程 render_expert_video 接口响应
- 检查本地 /api/v1/remote-download 代理是否可访问
- 检查远程导出目录写权限

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
8. remote_inference_server.py

这样可以先理解本地业务边界，再深入远程重计算细节。

---

## 10. 后续演进建议

优先级建议：

P0：
- 500MB 大文件分片上传与断点续传
- 导出任务异步化（任务查询与回调）

P1：
- 返回 GPU 监控字段（显存/利用率/温度）
- 推理与导出请求增加 request_id 做链路追踪

P2：
- fast/full 双模式切换
- 热点阈值与配色在前端可调

---

## 11. 结语

当前项目已经从“可跑通演示”升级到“可解释、可导出、可联调”的工程状态。
后续重点应从功能打通转向性能、稳定性与可观测性建设。

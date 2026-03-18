# Micro Action Recognition System

## 项目概述

- 目标：构建前后端分离的微动作识别系统。
- 当前阶段：系统集成阶段（前后端链路与可视化链路已打通）。
- 当前模型状态：仅有权重文件 `checkpoint-best.pth`，尚未接入训练时的真实模型结构代码。

## 截止目前已完成工作

### 1) 后端服务（FastAPI）

- 已完成基础 API 架构搭建。
- 已完成视频上传接口与静态可视化资源访问接口。
- 已完成时序概率与热力图数据输出格式。

已实现接口：

- `GET /health`：健康检查
- `POST /api/v1/infer`：上传视频并返回推理结果与可视化数据
- `GET /api/v1/assets/{filename}`：读取生成的帧图与热力图

### 2) 前端页面（Vue + Vite）

- 已完成上传面板（拖拽/选择文件）。
- 已完成结果总览（Top-1、置信度、时长）。
- 已完成时序概率曲线展示。
- 已完成热力图网格展示。
- 已优化网络错误提示，能提示后端未启动或请求超时。

### 3) 系统联调

- 已验证前后端基本链路可通。
- 已修复后端包导入路径问题（`ModuleNotFoundError: No module named 'app'`）。
- 已修复 VS Code 与命令行启动路径不一致导致的启动问题。

### 4) 环境与工程化

- 已统一使用 Anaconda 管理后端环境（环境名：`Micro_Action`）。
- 已补齐 VS Code 项目配置：`.vscode/settings.json`、`.vscode/tasks.json`、`.vscode/extensions.json`。
- 已补充 Windows 下前后端运行脚本：`run_backend.bat`、`run_frontend.bat`。

## 当前限制（请务必注意）

- 当前后端返回的“识别结果”是集成阶段占位逻辑（fallback），用于验证前后端链路，不代表真实模型精度。
- 出现 `Checkpoint not loaded. Running pure fallback integration pipeline.` 表示真实模型尚未加载。

## 迁移指南（真实模型接入）

- 请先阅读 `MODEL_INFERENCE_MIGRATION_GUIDE.md`，按“最小必需文件 + 依赖安装顺序 + Windows 失败兜底”执行迁移。

## 目录结构

- `backend/`：FastAPI 后端服务
- `frontend/`：Vue 前端页面
- `checkpoint-best.pth`：已训练模型权重
- `.vscode/`：VS Code 项目级配置

## 运行环境要求

### 后端

- 操作系统：Windows
- Python：建议 3.10（推荐）或 3.11
- 环境管理：Anaconda

### 前端

- Node.js：20.19+（Vite 7 要求）
- npm：随 Node.js 安装

## 一次性环境配置（首次执行）

### A. 后端环境（Anaconda）

```bash
cd /d d:\Project\Micro_Action_Recognition_System
conda create -n Micro_Action python=3.10 -y
conda activate Micro_Action
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

### B. 前端依赖

```bash
cd /d d:\Project\Micro_Action_Recognition_System\frontend
npm install
```

## 日常运行（每次开发）

### 方式 1：手动启动（推荐）

终端 1（后端）：

```bash
cd /d d:\Project\Micro_Action_Recognition_System
conda activate Micro_Action
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
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

## 下一步工作（重点）

### 达标检查表（系统集成与可视化）

| 模块       | 验收项                                      | 当前状态                       | 结论     | 下一动作                                         |
| ---------- | ------------------------------------------- | ------------------------------ | -------- | ------------------------------------------------ |
| 模型推理   | 替换 fallback，接入真实模型推理             | 仍存在 fallback 占位逻辑       | 未达标   | 接入训练时模型结构并加载 `checkpoint-best.pth` |
| 模型输出   | 返回 Top-1 + 关键帧索引 + 注意力矩阵        | 当前以 Top-1 与占位可视化为主  | 未达标   | 扩展推理返回字段与前端展示                       |
| 专业可视化 | Matplotlib/Seaborn 生成时序曲线（标关键帧） | 有基础时序图，关键帧标注未闭环 | 部分达标 | 后端生成带关键帧标注的静态图并落盘               |
| 专业可视化 | 特征维度热力矩阵                            | 当前热图为集成占位输出         | 部分达标 | 改为真实特征张量绘制热矩阵                       |
| 专业可视化 | 注意力权重图                                | 有占位 attention 展示          | 部分达标 | 输出真实 attention map 并统一色标                |
| 视频标注层 | OpenPose 轨迹叠加                           | 尚未闭环接入                   | 未达标   | 引入关键点检测并写入帧级轨迹                     |
| 视频标注层 | 类别置信度叠加                              | 已有基础数值展示               | 部分达标 | 在视频帧上叠加类别与置信度文本                   |
| 视频标注层 | 核心区域红框                                | 当前未统一输出到标注视频       | 未达标   | 根据注意力/运动区域生成红框并渲染                |
| 工程能力   | 500MB 上传支持                              | 未明确上限与错误码             | 未达标   | 增加文件大小限制、前后端双重校验                 |
| 工程能力   | PDF 导出                                    | 尚未实现                       | 未达标   | 增加报告模板与导出接口                           |
| 工程能力   | 历史记录检索                                | 尚未实现                       | 未达标   | 引入推理记录存储与检索接口                       |
| 工程能力   | GPU 显存与毫秒耗时                          | 当前展示不完整                 | 部分达标 | 采集显存占用与每次推理耗时                       |

### 下一步最小闭环（按顺序执行）

#### Step 1. 真实模型推理接入（先替换 fallback）

- 目标：后端输出真实推理结果，不再依赖占位流程。
- 必做项：
  - 补充训练期模型结构代码并成功加载 `checkpoint-best.pth`。
  - 对齐预处理流程（采样、resize、normalize、窗口长度）。
  - 返回 `top1`、`keyframe_indices`、`attention_matrix`。
- 完成判定：接口返回不再包含 fallback 提示，且 Top-1 可稳定复现。

#### Step 2. 专业可视化补齐（Matplotlib/Seaborn+Captum）

- 目标：输出可用于论文展示的标准图。
- 必做项：
  - 时序曲线：标注关键帧位置与峰值区间。
  - 特征热矩阵：按时间/特征维度绘制并标注颜色条。
  - 注意力权重图：统一色标、标题、时间轴刻度。
- 完成判定：接口返回的图像全部来自真实推理中间结果。

#### Step 3. 标注视频层实现（OpenPose + 多层信息）

- 目标：形成可播放的解释性结果视频。
- 必做项：
  - OpenPose 轨迹叠加。
  - 帧级类别与置信度文本。
  - 核心区域红框叠加。
- 完成判定：导出视频中同时包含轨迹、文本、红框三层信息。

#### Step 4. 工程能力补齐（交付级）

- 目标：满足演示与验收所需工程功能。
- 必做项：
  - 500MB 上传限制与友好错误提示。
  - PDF 报告导出（包含 Top-1、关键帧、可视化图、耗时）。
  - 历史记录检索（按时间/文件名/类别过滤）。
  - GPU 显存与毫秒级耗时展示。
- 完成判定：一次上传后可完成“识别 -> 可视化 -> 导出 -> 回查历史”的全链路。

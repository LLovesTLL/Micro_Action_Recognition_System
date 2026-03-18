# 真实模型推理迁移指南（VideoMambaPro）

## 适用场景

- 你已经有训练得到的权重文件（如 checkpoint-best.pth）。
- 当前后端是占位 fallback 推理，希望替换为真实模型推理。
- 训练项目使用了 VideoMambaPro，并依赖 mamba 与 causal-1d（通常对应 causal-conv1d）。

## 一、最小必需文件清单（从训练仓库拷贝到本仓库）

建议在 backend 下新增一个独立目录用于承载训练侧代码，例如：

- backend/app/ml/
  - models/
  - datasets/
  - utils/

最小必需文件（推理闭环）如下：

1. 模型结构
- videomambapro/models/videomambapro.py
- 该文件直接 import 的所有本地依赖（按源码 import 链补齐）

2. 预处理对齐
- datasets/video_transforms.py
- datasets/volume_transforms.py
- functional.py（若被上述流程调用）

3. 配置与映射
- 训练时的模型超参配置（model name、num_classes、num_frames、input_size、采样间隔）
- 类别索引到类别名映射文件（label map）

4. 权重
- checkpoint-best.pth

不需要迁移的训练侧文件：

- run_class_finetuning.py
- run_mae_pretraining.py
- run_videomambapro_pretraining.py
- run_umt_pretraining.py
- optim_factory.py（推理一般不需要）

## 二、依赖是否必须安装

结论：通常需要安装。

1. mamba（常见包名 mamba-ssm）
- 只要模型结构中使用了 Mamba Block，就必须安装。

2. causal-1d（常见实际包名 causal-conv1d）
- 若模型或 mamba 组件 import 了 causal_conv1d，则必须安装。

3. captum
- 仅在你做解释性可视化（IG、Saliency、GradCAM）时必须安装。
- 只做分类推理可不装。

快速判断方法：

- 在训练模型代码中搜索关键词：mamba_ssm、causal_conv1d。
- 只要 import 在默认路径下执行，就属于必装依赖。

## 三、推荐安装顺序（Conda: Micro_Action）

先决策：按 README1 的核心安装思路（PyTorch + Mamba 版本组合）执行，不直接照抄训练仓库 requirements.txt 全量安装。

- 原因：训练仓库 requirements.txt 包含大量训练/分布式依赖（如 deepspeed、apex、tensorflow、xformers），并非后端推理必需，且在 Windows 上更易冲突。
- 当前仓库已提供推理侧最小依赖文件：backend/requirements.real-infer.txt。

1. 安装基础依赖

- pip install -r backend/requirements.real-infer.txt

2. 安装训练模型常见推理依赖

- pip install timm einops

3. 安装解释可视化依赖（按需）

- pip install captum matplotlib seaborn

4. 安装 Mamba 相关依赖

- 优先安装 causal-conv1d
- 再安装 mamba-ssm

说明：

- mamba-ssm 与 causal-conv1d 在 Windows 可能出现编译问题，和 Python、PyTorch、CUDA 版本强相关。
- 如果 Windows 下持续失败，优先切换到 Linux 服务器或 WSL2，成功率更高。

## 四、Windows 失败兜底方案

触发条件：

- 安装 mamba-ssm 或 causal-conv1d 失败。
- 或安装成功但运行时报动态库/ABI 不兼容。

兜底路径：

1. 服务器准备（建议 Linux + CUDA）
- Python 3.10
- 与训练时尽可能一致的 PyTorch 与 CUDA 版本

2. 先完成纯推理链路
- 暂时不接 Captum，先保证 top1 输出稳定。

3. 再增加 Captum
- 先用轻量方法（Saliency/GradCAM）
- IG 逐步增加 steps，观察时延与显存。

## 五、后端改造落点（当前仓库）

1. 替换占位逻辑

- 现有占位服务文件：backend/app/services/model_service.py
- 新增真实模型加载器（建议）：backend/app/services/real_model_service.py

2. 推理服务接口保持不变

- 保持现有 API 返回结构，先替换内部打分逻辑。
- 首阶段最小目标：返回真实 top1，去掉 fallback 提示。

3. Captum 集成位置

- 可在 pipeline_service.py 或 visualization_service.py 增加解释分支。
- 建议加开关：ENABLE_CAPTUM=true/false，避免调试期卡死。

## 六、最小验收标准

1. /health 正常。
2. /api/v1/infer 不再输出 fallback 提示。
3. 同一测试视频多次推理，top1 结果稳定。
4. 若开启 Captum，接口可返回至少一种解释图且不 OOM。

## 七、建议你现在执行的顺序

1. 从训练仓库只迁移最小必需文件。
2. 在当前后端接通真实模型 top1 推理（先不加 Captum）。
3. 跑通后再接 Captum，并做显存与时延采样。
4. 若 Windows 依赖卡住，立即切 Linux 服务器，避免时间损耗。
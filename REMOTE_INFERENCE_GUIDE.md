# 远程推理架构部署指南 (Remote Inference Deployment Guide)

本指南针对“本机 Windows 展示 + 远程 Linux 推理”的架构，利用 SSH 隧道实现跨平台高性能视频微动作识别。

## 架构优势
- **本机零负载**：无需在本机安装 `mamba-ssm`, `causal-conv1d` 等重型依赖，显存占用为 0。
- **环境隔离**：利用服务器已有的训练环境进行推理，避免全量文件迁移。
- **安全传输**：通过 SSH 隧道加密传输视频数据到服务器，无需暴露公网端口。

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
conda activate videomambapro
pip install fastapi uvicorn python-multipart
```

### 4. 启动服务
```bash
python remote_inference_server.py
```
*服务默认运行在服务器的 `9000` 端口。*

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
- 预期返回：`{"status": "remote_server_alive", "gpu_available": true}`

### 2. 日志监控
- **本地后端日志**：若看到 `Inference completed by REMOTE Linux Server` 表示链路通畅。
- **远程服务器日志**：若看到上传请求并打印 `Loading Model...` 表示推理正在执行。

---

## 四、后续扩展
当你在服务器上完善了 `remote_inference_server.py` 中的 `run_inference` 逻辑（接入真实注意力图输出等）后，**本机代码无需任何改动**，刷新前端页面即可看到真实的推理结果。

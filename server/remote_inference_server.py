import http.server
import socketserver
import json
import torch
import os
import cv2
import numpy as np
import sys
import tempfile
import cgi
import time
import uuid
from urllib.parse import urlparse

# --- 1. 环境与路径配置 ---
PROJECT_ROOT = "/data/xcguo/Project/Micro_action"
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, "mamba"))
sys.path.append(os.path.join(PROJECT_ROOT, "causal-conv1d"))
CHECKPOINT_PATH = "/data/xcguo/Project/Micro_action/exp/mySelf/Thirteenth/checkpoint-best.pth"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
PORT = 9000
NUM_FRAMES = 16
INPUT_SIZE = 224
ATTENTION_GRID = 14
TOPK_RETURN = 5
ENABLE_TEMPORAL_PROBS = True
ATTENTION_NORMALIZE_MODE = "global"  # global | per_frame
HOTSPOT_THRESHOLD = 0.75
RENDER_OUTPUT_DIR = "/tmp/micro_action_renders"
RENDER_KEEP_MAX_FILES = 40

# 优先尝试这些较稳定的特征层名称（按顺序匹配）
FEATURE_HOOK_CANDIDATES = (
    "layers.31",
    "layers.31.norm",
    "layers.31.mixer.out_proj",
    "norm_f",
)

# 52类定义 (英文)
CLASSES_52 = [
    "shaking body", "sitting straightly", "shrugging", "turning around", "rising up",
    "bowing head", "head up", "tilting head", "turning head", "nodding",
    "shaking head", "scratching arms", "playing objects", "putting hands together",
    "rubbing hands", "pointing oneself", "clenching fist", "stretching arms",
    "retracting arms", "waving", "spreading hands", "hands touching fingers",
    "other finger movements", "illustrative gestures", "shaking legs", "curling legs",
    "spread legs", "closing legs", "crossing legs", "stretching feet",
    "retracting feet", "tiptoe", "scratching or touching neck", "scratching or touching chest",
    "scratching or touching back", "scratching or touching shoulder", "arms akimbo",
    "crossing arms", "playing or tidying hair", "scratching or touching hindbrain",
    "scratching or touching forehead", "scratching or touching face", "rubbing eyes",
    "touching nose", "touching ears", "covering face", "covering mouth",
    "pushing glasses", "patting legs", "touching legs", "scratching legs", "scratching feet"
]

# --- 2. 模型加载逻辑 ---
print(f">>> [Server] 正在从 {CHECKPOINT_PATH} 加载 VideoMambaPro Middle (16f)...")
model = None
_FEATURE_HOOK_HANDLE = None
_FEATURE_HOOK_LAYER = None
_FEATURE_HOOK_MODE = None
_LAST_FEATURE = None


def _ensure_render_dir():
    os.makedirs(RENDER_OUTPUT_DIR, exist_ok=True)


def _cleanup_render_dir(max_files=RENDER_KEEP_MAX_FILES):
    if not os.path.isdir(RENDER_OUTPUT_DIR):
        return
    files = [
        os.path.join(RENDER_OUTPUT_DIR, f)
        for f in os.listdir(RENDER_OUTPUT_DIR)
        if f.endswith(".mp4")
    ]
    if len(files) <= max_files:
        return
    files.sort(key=lambda p: os.path.getmtime(p))
    for p in files[:-max_files]:
        try:
            os.remove(p)
        except OSError:
            pass


def _pick_tensor(data):
    if torch.is_tensor(data):
        return data
    if isinstance(data, (list, tuple)):
        for item in data:
            tensor = _pick_tensor(item)
            if tensor is not None:
                return tensor
    if isinstance(data, dict):
        for item in data.values():
            tensor = _pick_tensor(item)
            if tensor is not None:
                return tensor
    return None


def _feature_hook(_module, _inputs, output):
    global _LAST_FEATURE
    tensor = _pick_tensor(output)
    if tensor is not None:
        _LAST_FEATURE = tensor.detach()


def _register_feature_hook(net):
    named = dict(net.named_modules())

    # 先按显式候选名匹配，尽可能保证跨版本稳定
    for cand in FEATURE_HOOK_CANDIDATES:
        if cand in named:
            handle = named[cand].register_forward_hook(_feature_hook)
            return handle, cand, "named_candidate"

    # 再按后缀匹配（容忍主干前缀变化）
    for name, module in named.items():
        if any(name.endswith(cand) for cand in FEATURE_HOOK_CANDIDATES):
            handle = module.register_forward_hook(_feature_hook)
            return handle, name, "suffix_candidate"

    candidates = []
    keywords = ("backbone", "encoder", "layer", "block", "stage", "mamba")

    for name, module in net.named_modules():
        lname = name.lower()
        if any(k in lname for k in keywords):
            candidates.append((name, module))

    if not candidates:
        return None, None, "none"

    # 选最后一个候选层，通常更接近高层语义特征
    selected_name, selected_module = candidates[-1]
    handle = selected_module.register_forward_hook(_feature_hook)
    return handle, selected_name, "keyword_fallback"


def _normalize_saliency(saliency, mode=ATTENTION_NORMALIZE_MODE):
    if mode == "global":
        s_min = saliency.amin()
        s_max = saliency.amax()
        saliency = (saliency - s_min) / (s_max - s_min + 1e-6)
        return saliency

    frame_min = saliency.amin(dim=(1, 2), keepdim=True)
    frame_max = saliency.amax(dim=(1, 2), keepdim=True)
    saliency = (saliency - frame_min) / (frame_max - frame_min + 1e-6)
    return saliency


def _to_attention_from_feature(feature_tensor, num_frames=NUM_FRAMES, grid_size=ATTENTION_GRID):
    if feature_tensor is None:
        return None

    ft = feature_tensor.detach().float().cpu()

    # 目标转换到 [T, H, W]，优先处理常见视频特征布局
    if ft.dim() == 5:
        # [B, C, T, H, W]
        if ft.size(2) == num_frames:
            saliency = ft.abs().mean(dim=1).squeeze(0)
        # [B, T, C, H, W]
        elif ft.size(1) == num_frames:
            saliency = ft.abs().mean(dim=2).squeeze(0)
        else:
            return None
    elif ft.dim() == 4:
        # [B, C, H, W]：无时序，复制到 T 帧
        frame_map = ft.abs().mean(dim=1).squeeze(0)
        saliency = frame_map.unsqueeze(0).repeat(num_frames, 1, 1)
    elif ft.dim() == 3:
        # [B, T, C] / [T, H, W] / [B, N, C](token 序列)
        if ft.size(1) == num_frames:
            vec = ft.squeeze(0).abs().mean(dim=-1).view(num_frames, 1, 1)
            saliency = vec.repeat(1, grid_size, grid_size)
        elif ft.size(0) == 1:
            # 常见于 ViT/Mamba 输出: [B, N, C]，其中 N = T * (grid * grid)
            token_count = int(ft.size(1))
            spatial_tokens = int(grid_size * grid_size)
            # 若包含 cls token（常见 N = 1 + T*H*W），先移除第一个 token
            if spatial_tokens > 0 and token_count % spatial_tokens != 0 and (token_count - 1) % spatial_tokens == 0:
                ft = ft[:, 1:, :]
                token_count = int(ft.size(1))

            if spatial_tokens > 0 and token_count % spatial_tokens == 0:
                t_infer = token_count // spatial_tokens
                token_map = ft.squeeze(0).abs().mean(dim=-1).view(t_infer, grid_size, grid_size)
                if t_infer != num_frames:
                        token_flat = token_map.permute(1, 2, 0).reshape(1, spatial_tokens, t_infer)
                        token_flat = torch.nn.functional.interpolate(
                            token_flat,
                            size=num_frames,
                            mode="linear",
                            align_corners=False,
                        )
                        token_map = token_flat.reshape(grid_size, grid_size, num_frames).permute(2, 0, 1)
                saliency = token_map
            else:
                return None
        elif ft.size(0) == num_frames:
            if ft.size(1) > 1 and ft.size(2) > 1:
                saliency = ft.abs()
            else:
                vec = ft.abs().mean(dim=-1).view(num_frames, 1, 1)
                saliency = vec.repeat(1, grid_size, grid_size)
        else:
            return None
    else:
        return None

    # 统一尺寸到 [T, grid, grid]
    saliency = torch.nn.functional.interpolate(
        saliency.unsqueeze(1),
        size=(grid_size, grid_size),
        mode="bilinear",
        align_corners=False,
    ).squeeze(1)

    saliency = _normalize_saliency(saliency, mode=ATTENTION_NORMALIZE_MODE)

    return saliency.tolist()


def _to_attention_from_input(input_tensor, grid_size=ATTENTION_GRID):
    # 输入兜底注意力：基于每帧像素能量
    saliency = input_tensor.detach().float().cpu().abs().mean(dim=1).squeeze(0)  # [T, H, W]
    saliency = torch.nn.functional.interpolate(
        saliency.unsqueeze(1),
        size=(grid_size, grid_size),
        mode="bilinear",
        align_corners=False,
    ).squeeze(1)
    saliency = _normalize_saliency(saliency, mode=ATTENTION_NORMALIZE_MODE)
    return saliency.tolist()


def _extract_logits(output):
    logits = _pick_tensor(output)
    if logits is None:
        raise ValueError("模型输出中未找到可用 Tensor")
    if logits.dim() == 1:
        logits = logits.unsqueeze(0)
    if logits.dim() != 2:
        raise ValueError(f"模型输出 Tensor 维度异常: {tuple(logits.shape)}")
    return logits


def _build_temporal_probs(input_tensor, num_frames=NUM_FRAMES):
    # 逐帧构造“单帧重复 clip”并前向，得到真实模型输出的时序概率曲线
    temporal_probs = []
    for t in range(num_frames):
        frame_t = input_tensor[:, :, t:t + 1, :, :]
        clip_t = frame_t.repeat(1, 1, num_frames, 1, 1)
        logits_t = _extract_logits(model(clip_t))
        probs_t = torch.nn.functional.softmax(logits_t, dim=1).squeeze(0)
        temporal_probs.append(probs_t.tolist())
    return temporal_probs


def _safe_label(label_id):
    if 0 <= label_id < len(CLASSES_52):
        return CLASSES_52[label_id]
    return f"unknown_{label_id}"


def _extract_attention_hotspots(attention_matrix, threshold=HOTSPOT_THRESHOLD):
    # 输出每帧热点框，坐标归一化到 [0, 1]
    if attention_matrix is None:
        return []

    hotspots = []
    for fi, frame_map in enumerate(attention_matrix):
        arr = np.asarray(frame_map, dtype=np.float32)
        if arr.ndim != 2:
            continue
        arr = np.clip(arr, 0.0, 1.0)
        mask = (arr >= threshold).astype(np.uint8) * 255
        if mask.max() == 0:
            y, x = np.unravel_index(np.argmax(arr), arr.shape)
            h, w = arr.shape
            x1 = max(0, x - 1)
            y1 = max(0, y - 1)
            x2 = min(w - 1, x + 1)
            y2 = min(h - 1, y + 1)
            score = float(arr[y, x])
        else:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            best = max(contours, key=cv2.contourArea)
            bx, by, bw, bh = cv2.boundingRect(best)
            x1, y1 = bx, by
            x2, y2 = bx + bw - 1, by + bh - 1
            score = float(arr[by:by + bh, bx:bx + bw].mean())

        h, w = arr.shape
        hotspots.append({
            "frame_index": int(fi),
            "x1": float(x1 / max(1, w - 1)),
            "y1": float(y1 / max(1, h - 1)),
            "x2": float(x2 / max(1, w - 1)),
            "y2": float(y2 / max(1, h - 1)),
            "score": score,
        })

    return hotspots


def _nearest_sample_idx(frame_idx, sampled_indices):
    if not sampled_indices:
        return 0
    return int(np.argmin([abs(frame_idx - s) for s in sampled_indices]))


def _render_expert_video(
    input_video_path,
    output_video_path,
    prediction,
    confidence,
    attention_matrix,
    sampled_indices,
    hotspots,
):
    cap = cv2.VideoCapture(str(input_video_path))
    if not cap.isOpened():
        raise ValueError("无法打开输入视频，导出失败")

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    if fps <= 1e-6:
        fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise ValueError("无法创建导出视频文件")

    hot_by_sample = {h["frame_index"]: h for h in hotspots}
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        sample_slot = _nearest_sample_idx(frame_idx, sampled_indices)

        if attention_matrix is not None and 0 <= sample_slot < len(attention_matrix):
            att_map = np.asarray(attention_matrix[sample_slot], dtype=np.float32)
            att_map = np.clip(att_map, 0.0, 1.0)
            att_up = cv2.resize(att_map, (width, height), interpolation=cv2.INTER_CUBIC)
            heat = np.uint8(att_up * 255.0)
            heat = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
            frame = cv2.addWeighted(frame, 0.68, heat, 0.32, 0.0)

        hs = hot_by_sample.get(sample_slot)
        if hs is not None:
            x1 = int(hs["x1"] * (width - 1))
            y1 = int(hs["y1"] * (height - 1))
            x2 = int(hs["x2"] * (width - 1))
            y2 = int(hs["y2"] * (height - 1))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (30, 50, 240), 2)

        label_text = f"{prediction} ({confidence * 100:.1f}%)"
        cv2.putText(frame, label_text, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (20, 220, 20), 2, cv2.LINE_AA)
        cv2.putText(frame, f"frame={frame_idx}", (16, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2, cv2.LINE_AA)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()

    return {
        "frames": frame_idx,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_sec": (frame_idx / fps) if fps > 1e-6 else None,
    }


def _run_inference_from_video_path(tmp_path):
    global _LAST_FEATURE

    t_pre0 = time.perf_counter()
    preprocess_data = preprocess_video(tmp_path)
    if preprocess_data is None:
        raise ValueError("视频无法读取或损坏")

    input_tensor = preprocess_data["tensor"].to(DEVICE)
    sampled_indices = preprocess_data["sampled_indices"]
    print(f">>> [Debug] 视频已转换为 Tensor, 均值: {input_tensor.mean():.4f}")
    preprocess_ms = (time.perf_counter() - t_pre0) * 1000.0

    t0 = time.perf_counter()
    _LAST_FEATURE = None
    with torch.no_grad():
        output = model(input_tensor)
        logits_raw = _extract_logits(output)
        probs = torch.nn.functional.softmax(logits_raw, dim=1)
        conf, pred = torch.max(probs, dim=1)
    infer_ms = (time.perf_counter() - t0) * 1000.0

    t_post0 = time.perf_counter()
    attention_matrix = _to_attention_from_feature(_LAST_FEATURE)
    attention_source = "feature_hook"
    if attention_matrix is None:
        attention_matrix = _to_attention_from_input(input_tensor)
        attention_source = "input_fallback"

    attention_hotspots = _extract_attention_hotspots(attention_matrix)

    temporal_source = "disabled"
    temporal_probs = None
    temporal_infer_ms = 0.0
    if ENABLE_TEMPORAL_PROBS:
        t_temporal0 = time.perf_counter()
        try:
            with torch.no_grad():
                temporal_probs = _build_temporal_probs(input_tensor)
            temporal_source = "frame_repeat_forward"
        except Exception as temporal_e:
            print(f">>> [Warn] temporal_probs 生成失败，回退静态概率: {temporal_e}")
            temporal_probs = [probs.squeeze(0).tolist() for _ in range(NUM_FRAMES)]
            temporal_source = "static_fallback"
        temporal_infer_ms = (time.perf_counter() - t_temporal0) * 1000.0

    logits_raw_1d = logits_raw.squeeze(0)
    probs_1d = probs.squeeze(0)
    topk_conf, topk_idx = torch.topk(probs_1d, k=min(TOPK_RETURN, probs_1d.numel()))
    topk = [
        {
            "label_id": int(idx.item()),
            "label": _safe_label(int(idx.item())),
            "confidence": float(score.item()),
        }
        for score, idx in zip(topk_conf, topk_idx)
    ]

    label_id = int(pred.item())
    confidence = float(conf.item())
    label_name = _safe_label(label_id)
    postprocess_ms = (time.perf_counter() - t_post0) * 1000.0
    total_time_ms = preprocess_ms + infer_ms + temporal_infer_ms + postprocess_ms

    return {
        "prediction": label_name,
        "confidence": confidence,
        "label_id": label_id,
        "logits": probs_1d.tolist(),
        "logits_raw": logits_raw_1d.tolist(),
        "probs": probs_1d.tolist(),
        "num_classes": int(probs_1d.numel()),
        "attention_matrix": attention_matrix,
        "attention_shape": [NUM_FRAMES, ATTENTION_GRID, ATTENTION_GRID],
        "attention_source": attention_source,
        "attention_hook_layer": _FEATURE_HOOK_LAYER,
        "attention_hook_mode": _FEATURE_HOOK_MODE,
        "attention_normalization_mode": ATTENTION_NORMALIZE_MODE,
        "attention_hotspots": attention_hotspots,
        "attention_hotspot_threshold": HOTSPOT_THRESHOLD,
        "topk": topk,
        "temporal_probs": temporal_probs,
        "temporal_probs_shape": [NUM_FRAMES, int(probs_1d.numel())] if temporal_probs is not None else None,
        "temporal_source": temporal_source,
        "temporal_frame_indices": sampled_indices,
        "num_total_frames": preprocess_data["num_total_frames"],
        "video_fps": preprocess_data["fps"],
        "video_duration_sec": preprocess_data["duration_sec"],
        "preprocess_time_ms": round(preprocess_ms, 3),
        "inference_time_ms": round(infer_ms, 3),
        "temporal_inference_time_ms": round(temporal_infer_ms, 3),
        "postprocess_time_ms": round(postprocess_ms, 3),
        "total_time_ms": round(total_time_ms, 3),
        "device": DEVICE,
        "status": "success",
    }


try:
    # 确保导入路径正确
    from videomambapro.models.videomambapro import videomambapro_m16_ssv2 as create_model
    model = create_model(num_classes=52, num_frames=NUM_FRAMES)
    
    checkpoint = torch.load(CHECKPOINT_PATH, map_location="cpu")
    state_dict = checkpoint['model'] if 'model' in checkpoint else checkpoint
    
    # 加载权重
    msg = model.load_state_dict(state_dict, strict=True)
    model.to(DEVICE).eval()
    print(f">>> [Server] 真实模型加载成功: {msg}")

    _FEATURE_HOOK_HANDLE, _FEATURE_HOOK_LAYER, _FEATURE_HOOK_MODE = _register_feature_hook(model)
    if _FEATURE_HOOK_LAYER:
        print(f">>> [Server] 特征钩子已挂载: {_FEATURE_HOOK_LAYER} (mode={_FEATURE_HOOK_MODE})")
    else:
        print(">>> [Server] 未找到可挂钩特征层，将使用输入兜底注意力图")
except Exception as e:
    print(f">>> [Server] 模型加载失败!!! 错误信息: {e}")
    sys.exit(1)

# --- 3. 视频预处理函数 ---
def preprocess_video(video_path, num_frames=NUM_FRAMES, size=INPUT_SIZE):
    cap = cv2.VideoCapture(str(video_path))
    v_len = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if v_len <= 0:
        cap.release()
        return None

    fps = float(cap.get(cv2.CAP_PROP_FPS))
    duration_sec = (v_len / fps) if fps > 1e-6 else None

    # 均匀采样 16 帧
    indices = np.linspace(0, v_len - 1, num_frames).astype(int).tolist()
    index_set = set(indices)
    frames = []
    sampled_indices = []
    
    for i in range(v_len):
        ret, frame = cap.read()
        if not ret: break
        if i in index_set:
            frame = cv2.resize(frame, (size, size))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame)
            sampled_indices.append(int(i))
            if len(frames) == num_frames: break
    cap.release()

    # 补帧（极端视频短的情况）
    while len(frames) < num_frames:
        frames.append(frames[-1] if frames else np.zeros((size, size, 3), dtype=np.uint8))
        sampled_indices.append(sampled_indices[-1] if sampled_indices else 0)
        
    # 构建 Tensor [1, 3, 16, 224, 224]
    v_tensor = np.stack(frames) # [T, H, W, C]
    v_tensor = torch.from_numpy(v_tensor).float() / 255.0
    v_tensor = v_tensor.permute(3, 0, 1, 2).unsqueeze(0) # [1, C, T, H, W]
    
    # 标准化
    mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1, 1)
    return {
        "tensor": (v_tensor - mean) / std,
        "sampled_indices": sampled_indices,
        "num_total_frames": v_len,
        "fps": fps,
        "duration_sec": duration_sec,
    }

# --- 4. HTTP 请求处理器 ---
class VideoMambaInferenceHandler(http.server.BaseHTTPRequestHandler):
    def _send_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            health_data = {
                "status": "remote_server_alive",
                "device": DEVICE,
                "model_loaded": model is not None,
                "gpu_available": torch.cuda.is_available(),
                "num_frames": NUM_FRAMES,
                "feature_hook_layer": _FEATURE_HOOK_LAYER,
                "feature_hook_mode": _FEATURE_HOOK_MODE,
                "temporal_probs_enabled": ENABLE_TEMPORAL_PROBS,
                "attention_normalization_mode": ATTENTION_NORMALIZE_MODE,
                "render_output_dir": RENDER_OUTPUT_DIR,
            }
            self._send_response(health_data)
        elif parsed.path.startswith('/download/'):
            filename = os.path.basename(parsed.path[len('/download/'):])
            if not filename:
                self._send_response({"status": "error", "message": "invalid download path"}, status=400)
                return
            full_path = os.path.join(RENDER_OUTPUT_DIR, filename)
            if not os.path.exists(full_path):
                self._send_response({"status": "error", "message": "file not found"}, status=404)
                return

            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(os.path.getsize(full_path)))
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            with open(full_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self._send_response({"status": "error", "message": "Not Found"}, status=404)

    def do_POST(self):
        if self.path in ('/predict', '/render_expert_video'):
            print(f"\n>>> [Server] 收到请求: {self.path}")

            ctype, pdict = cgi.parse_header(self.headers.get('content-type'))
            if ctype != 'multipart/form-data':
                self._send_response({"status": "error", "message": "Content-Type must be multipart/form-data"}, status=400)
                return

            pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
            fields = cgi.parse_multipart(self.rfile, pdict)
            file_items = fields.get('file')
            if not file_items:
                self._send_response({"status": "error", "message": "缺少 file 字段"}, status=400)
                return
            video_bytes = file_items[0]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                tmp.write(video_bytes)
                tmp_path = tmp.name

            try:
                result = _run_inference_from_video_path(tmp_path)
                print(f">>> [Server] 推理完成: {result['prediction']} (置信度: {result['confidence']:.4f})")

                if self.path == '/predict':
                    self._send_response(result)
                    return

                # /render_expert_video: 生成标注视频并返回下载地址
                _ensure_render_dir()
                _cleanup_render_dir()
                render_id = str(uuid.uuid4())
                render_name = f"expert_{render_id}.mp4"
                render_path = os.path.join(RENDER_OUTPUT_DIR, render_name)

                render_meta = _render_expert_video(
                    input_video_path=tmp_path,
                    output_video_path=render_path,
                    prediction=result["prediction"],
                    confidence=result["confidence"],
                    attention_matrix=result.get("attention_matrix"),
                    sampled_indices=result.get("temporal_frame_indices") or [],
                    hotspots=result.get("attention_hotspots") or [],
                )

                self._send_response({
                    "status": "success",
                    "render_id": render_id,
                    "render_filename": render_name,
                    "download_url": f"/download/{render_name}",
                    "render_meta": render_meta,
                    "inference": result,
                })
            except Exception as e:
                print(f">>> [Error] 请求处理出错: {e}")
                self._send_response({"status": "error", "message": str(e)}, status=500)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            self._send_response({"status": "error", "message": "Not Found"}, status=404)

# --- 5. 启动点 ---
class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"Starting Remote VideoMambaPro Server on {PORT}...")
    with ThreadingTCPServer(("", PORT), VideoMambaInferenceHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n>>> Server Stopped.")
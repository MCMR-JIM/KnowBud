# LoopTutor 本地多模态模型部署文档 (Gemma 3)

## 概述

LoopTutor 支持两种 LLM 模式：

| 模式 | 环境变量 | 说明 |
|---|---|---|
| **远程 API**（默认） | `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 调用 OpenAI 兼容 API |
| **本地模型** | `LOCAL_MODEL_ENABLED=true` | 加载本地 Gemma 3 多模态模型 |

本地模型模式下，知识图谱 pipeline 的 LLM 调用可切换到本地推理，减少 API 延迟和成本。当前为**实验性功能**，默认关闭，不影响现有 OpenAI 流程。

---

## 环境配置

在项目根目录 `.env` 文件中追加：

```bash
# 本地模型开关
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_PATH=E:\Programme\Gemma\cache\models--google--gemma-3-4b-it\snapshots\<hash>
LOCAL_MODEL_DEVICE=cuda:0
LOCAL_MODEL_DTYPE=bfloat16
LOCAL_MODEL_LOAD_8BIT=false
LOCAL_MODEL_MAX_NEW_TOKENS=500
LOCAL_MODEL_TEMPERATURE=0.3
LOCAL_MODEL_TIMEOUT=120
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOCAL_MODEL_ENABLED` | `false` | 是否启用本地模型 |
| `LOCAL_MODEL_PATH` | - | 模型快照目录（snapshots 下的 hash 文件夹） |
| `LOCAL_MODEL_DEVICE` | `cuda:0` | 设备：`cuda:0` / `cpu` |
| `LOCAL_MODEL_DTYPE` | `bfloat16` | 模型精度：`bfloat16` / `float16` / `float32` |
| `LOCAL_MODEL_LOAD_8BIT` | `false` | 使用 8bit 量化加载（降低显存，当前不推荐） |
| `LOCAL_MODEL_MAX_NEW_TOKENS` | `500` | 每次推理最大输出 token 数 |
| `LOCAL_MODEL_TEMPERATURE` | `0.3` | 生成温度（0=确定性，1=随机） |
| `LOCAL_MODEL_TIMEOUT` | `120` | 单次 LLM 调用超时（秒） |

---

## 硬件要求

| 硬件 | 最低 | 推荐 |
|---|---|---|
| 显存 | 8 GB | 12 GB+ |
| 内存 | 16 GB | 32 GB |
| 磁盘 | 10 GB 自由空间 | 20 GB+ |
| GPU | NVIDIA RTX 3060+ | RTX 4070+ |
| CUDA | 12.1+ | 12.4+ |

**测试环境**：RTX 4070 12GB，bfloat16 加载 Gemma-3-4B-it 占用约 8GB 显存，推理速度约 20-30 tokens/s。

---

## 下载步骤

### 1. 安装依赖

```powershell
# 进入项目虚拟环境
.venv\Scripts\Activate.ps1

# 安装 PyTorch CUDA 版
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 安装 transformers
pip install "transformers>=4.50" accelerate
```

### 2. HuggingFace 认证

1. 浏览器打开 https://huggingface.co/google/gemma-3-4b-it ，登录后点击 "Access repository" 接受许可
2. 获取 Token：https://huggingface.co/settings/tokens
3. 终端登录：
```powershell
huggingface-cli login
```

### 3. 下载模型

```python
import torch
from transformers import AutoProcessor, Gemma3ForConditionalGeneration

model = Gemma3ForConditionalGeneration.from_pretrained(
    'google/gemma-3-4b-it',
    dtype=torch.bfloat16,
    device_map='cuda:0'
)
processor = AutoProcessor.from_pretrained('google/gemma-3-4b-it')

# 获取快照 hash
import os
cache = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
model_dir = os.path.join(cache, 'models--google--gemma-3-4b-it', 'snapshots')
hash_dir = os.listdir(model_dir)[0]
model_path = os.path.join(model_dir, hash_dir)
print(f'LOCAL_MODEL_PATH={model_path}')
```

将输出的 `LOCAL_MODEL_PATH` 填入 `.env`。

---

## 验证

```python
import torch
LOCAL = r'你的模型路径'
from transformers import AutoProcessor, Gemma3ForConditionalGeneration

model = Gemma3ForConditionalGeneration.from_pretrained(
    LOCAL, dtype=torch.bfloat16, device_map='cuda:0', local_files_only=True
)
processor = AutoProcessor.from_pretrained(LOCAL, local_files_only=True)

# 文本测试
messages = [{'role':'user','content':[{'type':'text','text':'用中文回答：什么是机器学习？'}]}]
inputs = processor.apply_chat_template(messages, add_generation_prompt=True, 
    tokenize=True, return_dict=True, return_tensors='pt').to('cuda:0', dtype=torch.bfloat16)
with torch.inference_mode():
    out = model.generate(**inputs, max_new_tokens=50, do_sample=False)
print(processor.decode(out[0][inputs['input_ids'].shape[-1]:], skip_special_tokens=True))

# 多模态测试
messages2 = [{'role':'user','content':[
    {'type':'image','url':'https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/p-blog/candy.JPG'},
    {'type':'text','text':'What animal is on the candy?'}
]}]
inputs2 = processor.apply_chat_template(messages2, add_generation_prompt=True,
    tokenize=True, return_dict=True, return_tensors='pt').to('cuda:0', dtype=torch.bfloat16)
with torch.inference_mode():
    out2 = model.generate(**inputs2, max_new_tokens=20, do_sample=False)
print(processor.decode(out2[0][inputs2['input_ids'].shape[-1]:], skip_special_tokens=True))
```

预期输出：中文描述机器学习 + 英文识别乌龟 `Turtle`。

---

## 已知问题

1. **4bit/8bit 量化不可用**：`bitsandbytes` 量化导致输出为空白或乱码。当前使用 bfloat16 直接加载。
2. **不支持 `do_sample=True`**：Gemma 3 的采样生成在 4B 模型上不稳定，推荐 `do_sample=False`。
3. **首次加载慢**：shard 加载约 2-4 分钟，后续挂载进程后可在内存中保持。
4. **不支持 GGUF**：`llama-cpp-python` CUDA DLL 缺失，CPU 版不可行。

---

## 集成计划

- [ ] `src/services/local_llm.py`：封装本地模型加载和推理
- [ ] 环境变量驱动的模式切换（local vs remote API）
- [ ] 与知识图谱 pipeline 的批量 LLM 调用对接
- [ ] RAG-Anything 文档解析集成

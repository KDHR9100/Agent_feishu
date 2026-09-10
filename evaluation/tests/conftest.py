"""evaluation 模块测试（pytest evaluation/ 即可运行）。"""

import os
import sys
from pathlib import Path

# 保证仓库根目录在 sys.path（pytest evaluation/ 从任意 CWD 都能 import evaluation）
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# CI 默认 mock：任何 LLM 都不会被真实调用
os.environ.setdefault("EVAL_MODE", "mock")

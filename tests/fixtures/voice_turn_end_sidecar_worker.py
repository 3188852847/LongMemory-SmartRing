"""仅供 AC 管道隔离测试的无模型/无网络子进程。"""

import argparse
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/development/xiaozhi"))
from voice_turn_end_sidecar import HEADER, _read_exact, _reply, worker_loop

parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="normal")
args = parser.parse_args()

if args.mode == "nohandshake":
    time.sleep(30)
elif args.mode == "unavailable":
    _reply(sys.stdout.buffer, {"version": 1, "status": "unavailable"})
elif args.mode == "wrongid":
    _reply(sys.stdout.buffer, {"version": 1, "status": "ready", "provider": "CPUExecutionProvider"})
    _, sequence, size = HEADER.unpack(_read_exact(sys.stdin.buffer, HEADER.size))
    _read_exact(sys.stdin.buffer, size)
    _reply(sys.stdout.buffer, {"version": 1, "status": "ok", "id": sequence + 1,
                              "probability": 0.9, "processing_ms": 0})
    time.sleep(30)
else:
    class Detector:
        def predict(self, pcm):
            assert "PYTHONPATH" not in os.environ
            assert "PYTHONHOME" not in os.environ
            assert os.environ["USE_TORCH"] == "0"
            assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"
            assert "torch" not in sys.modules
            if args.mode == "slow":
                time.sleep(0.4)
            elif args.mode == "brief":
                time.sleep(0.05)
            elif args.mode == "error":
                raise RuntimeError("must not expose request payload or original error")
            return 0.9

    raise SystemExit(worker_loop(Detector(), sys.stdin.buffer, sys.stdout.buffer))

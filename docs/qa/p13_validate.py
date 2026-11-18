"""Run offline P1.3 checks from any working directory; save UTF-8 evidence."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
python = ROOT / "apps/api/.venv/Scripts/python.exe"
commands = [
    ("backend", [str(python), "docs/qa/p13_backend_test.py"]),
    ("frontend", [shutil.which("node"), "--test", "docs/qa/p13_frontend_test.mjs"]),
    ("build", [shutil.which("npm.cmd"), "--prefix", "apps/web", "run", "build"]),
]
result = {"timestamp": datetime.now(timezone.utc).isoformat(), "checks": []}
for name, command in commands:
    started = time.monotonic()
    process = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = re.sub(r"\x1b\[[0-9;]*m", "", process.stdout.decode("utf-8", "replace"))
    (HERE / f"p13-{name}-test.log").write_text(log, encoding="utf-8")
    result["checks"].append({"name": name, "exitCode": process.returncode, "elapsedSeconds": round(time.monotonic() - started, 2)})
    print(f"{name}: exit={process.returncode}")
result["passed"] = all(item["exitCode"] == 0 for item in result["checks"])
(HERE / "p13-validation-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
raise SystemExit(0 if result["passed"] else 1)

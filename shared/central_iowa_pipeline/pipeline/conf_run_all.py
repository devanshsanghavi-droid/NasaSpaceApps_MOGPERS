"""conf module: run the whole confounder/weather pipeline in order (each step caches raw downloads).
.venv/bin/python pipeline/conf_run_all.py"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for s in ["conf_weather.py", "conf_terrain.py", "conf_soils.py", "conf_imerg.py", "conf_assemble.py"]:
    print("==>", s, flush=True)
    subprocess.run([sys.executable, str(HERE / s)], check=True)

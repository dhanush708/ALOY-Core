import subprocess
import time
import httpx
import sys
import psutil

exe_path = r"dist\ALOY\ALOY.exe"

print("Starting ALOY.exe...")
proc = subprocess.Popen([exe_path])

started = False
for _ in range(15):
    time.sleep(1)
    try:
        r = httpx.get("http://127.0.0.1:8000/health", timeout=1.0)
        if r.status_code == 200:
            print("SUCCESS: ALOY is serving on port 8000!")
            started = True
            break
    except Exception:
        pass

if not started:
    print("FAILED: ALOY did not start within 15 seconds.")

print("Killing process tree...")
try:
    parent = psutil.Process(proc.pid)
    for child in parent.children(recursive=True):
        child.kill()
    parent.kill()
except Exception as e:
    print(f"Error killing process: {e}")

sys.exit(0 if started else 1)

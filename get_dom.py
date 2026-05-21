import urllib.request
import time
import subprocess
import threading
import os

def start_server():
    os.system("streamlit run app.py --server.port 8503 --server.headless true > /dev/null 2>&1")

threading.Thread(target=start_server, daemon=True).start()
time.sleep(4)
print("done starting")

"""
iHIM Silent Runner - No console window
Used for background/startup execution
"""
import sys
import os

# Change to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Add to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import uvicorn
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])
    import uvicorn

# Guard required for Windows multiprocessing (uvicorn reload uses spawn)
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=7777,
        reload=True,
        log_level="error"
    )

"""
iHIM - Launch the Command Center

Run with: python run.py
Open browser to: http://localhost:7777
"""
import subprocess
import sys
import os
from pathlib import Path


def get_venv_python():
    """Get the path to the venv Python executable (cross-platform)."""
    base = Path(__file__).parent / ".venv"
    if sys.platform == "win32":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def ensure_venv():
    """Ensure we're running in the virtual environment."""
    venv_python = get_venv_python()

    # Check if venv exists
    if not venv_python.exists():
        print()
        print("  Virtual environment not found!")
        print("  Run this once to set it up:")
        print()
        if sys.platform == "win32":
            print("    python -m venv .venv")
            print("    .venv\\Scripts\\activate")
            print("    pip install -r requirements.txt")
        else:
            print("    python3 -m venv .venv")
            print("    source .venv/bin/activate")
            print("    pip install -r requirements.txt")
        print()
        sys.exit(1)

    # If not running from venv, re-launch with venv Python
    if not sys.prefix.endswith(".venv"):
        os.chdir(Path(__file__).parent)
        os.execv(str(venv_python), [str(venv_python), __file__] + sys.argv[1:])


def check_and_install_deps():
    """Verify critical packages are installed; auto-install if missing."""
    critical = ["fastapi", "uvicorn", "sounddevice", "pyaudiowpatch", "numpy"]
    missing = []
    for pkg in critical:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"  Missing packages: {', '.join(missing)}")
        print("  Auto-installing from requirements.txt...")
        req_file = Path(__file__).parent / "requirements.txt"
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"
        ])
        print("  Done.")


def main():
    ensure_venv()
    check_and_install_deps()

    import webbrowser
    import time
    import threading

    print()
    print("  +-----------------------------+")
    print("  |           iHIM              |")
    print("  |      Command Center         |")
    print("  +-----------------------------+")
    print()
    print("  Starting server at http://localhost:7777")
    print("  Press Ctrl+C to stop")
    print()

    # Open browser after short delay (skip if supervised)
    skip_browser = os.environ.get('IHIM_SUPERVISED') == '1'
    if not skip_browser:
        def open_browser():
            time.sleep(1.5)
            webbrowser.open("http://localhost:7777")

        threading.Thread(target=open_browser, daemon=True).start()

    # Run server with proper hot reload
    import uvicorn
    from pathlib import Path

    # Get the IHIM directory
    ihim_dir = Path(__file__).parent

    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=7777,
        reload=True,
        reload_dirs=[str(ihim_dir)],  # Watch the entire IHIM directory
        reload_includes=["*.py", "*.html", "*.css", "*.js"],  # Watch these file types
        log_level="warning"
    )


if __name__ == "__main__":
    main()

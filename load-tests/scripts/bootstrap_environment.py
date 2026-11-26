"""Create an isolated Python without requiring the host's ensurepip package.

Stdlib only: this must run before installing any harness requirements.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import venv


def create_environment(destination):
    destination = Path(destination).resolve()
    # Reuses a partial venv left by a failed ensurepip, without deleting user files.
    venv.EnvBuilder(with_pip=False, clear=False).create(destination)
    python = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-c", "import sys; assert sys.prefix != sys.base_prefix"], check=True)
    return python


def install_requirements(python, requirements, env):
    """pip --python can manage a no-pip target; otherwise bootstrap pip there only."""
    python, requirements = str(python), str(requirements)
    candidates = [[sys.executable, "-m", "pip"]]
    command = shutil.which("pip") or shutil.which("pip3")
    if command:
        candidates.append([command])
    for manager in candidates:
        try:
            supported = subprocess.run([*manager, "--python", python, "--version"], env=env,
                                       capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if supported.returncode == 0:
            subprocess.run([*manager, "--python", python, "install", "--disable-pip-version-check",
                            "-r", requirements], env=env, check=True)
            return
    # The host might have neither pip nor a recent --python option. Never install into kernel Python.
    target = Path(python).resolve().parent.parent / "bootstrap-get-pip.py"
    try:
        with urllib.request.urlopen("https://bootstrap.pypa.io/get-pip.py", timeout=90) as response:
            target.write_bytes(response.read())
        subprocess.run([python, str(target), "--disable-pip-version-check"], env=env, check=True)
    finally:
        target.unlink(missing_ok=True)
    subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements],
                   env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    python = create_environment(args.venv)
    install_requirements(python, args.requirements, env)
    print("Isolated Python:", python, flush=True)
    subprocess.run([str(python), "-c", "from importlib.metadata import version; "
                    "import wrapt; print({n:version(n) for n in ['locust','psutil','psycopg','requests','PyYAML','bcrypt','wrapt']})"],
                   env=env, check=True)


if __name__ == "__main__":
    main()

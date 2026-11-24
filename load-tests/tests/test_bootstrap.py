"""Regression: Kaggle Python can create venvs while its ensurepip is unavailable."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class BootstrapTest(unittest.TestCase):
    def test_environment_creation_never_invokes_ensurepip_and_can_resume(self):
        from bootstrap_environment import create_environment
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temporary:
            destination = Path(temporary) / "venv"
            with patch.object(venv.EnvBuilder, "_setup_pip", side_effect=RuntimeError("ensurepip unavailable")):
                python = create_environment(destination)
                self.assertTrue(python.is_file())
                # A previous failed ensurepip attempt leaves a usable no-pip venv; retry must work.
                self.assertEqual(create_environment(destination), python)
            result = subprocess.run([str(python), "-c", "import sys; assert sys.prefix != sys.base_prefix"],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_manager_installs_into_target_python_not_kernel(self):
        from bootstrap_environment import install_requirements
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="pip 25.0", stderr="")
        with patch("bootstrap_environment.subprocess.run", side_effect=run):
            install_requirements(Path("/isolated/bin/python"), ROOT / "requirements-kaggle.txt", {})
        install = next(command for command in calls if "install" in command)
        self.assertIn("--python", install)
        self.assertEqual(Path(install[install.index("--python") + 1]), Path("/isolated/bin/python"))

    def test_existing_host_pip_can_manage_real_no_pip_environment(self):
        from bootstrap_environment import create_environment, install_requirements
        validation = Path(os.environ.get("BB_VALIDATION_DIR", ROOT / ".validation"))
        validation.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=validation) as temporary:
            root = Path(temporary)
            python = create_environment(root / "venv")
            requirements = root / "empty-requirements.txt"
            requirements.write_text("# No downloads: exercise real pip --python dispatch only\n")
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
            install_requirements(python, requirements, env)
            checked = subprocess.run([str(python), "-c", "import sys; assert sys.prefix != sys.base_prefix"],
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()

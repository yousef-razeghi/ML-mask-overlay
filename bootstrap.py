"""
bootstrap.py
------------
Make sure the handful of third-party packages the cropper needs are available
in the running kernel. On NOMAD NORTH most of them already are; anything that is
missing gets pip-installed quietly so there is no manual setup step.

Usage (top of the notebook):

    from bootstrap import ensure_requirements
    ensure_requirements()
"""
import importlib
import subprocess
import sys

# (import name, pip install name)
_REQUIRED = [
    ("numpy", "numpy"),
    ("tifffile", "tifffile"),
    ("matplotlib", "matplotlib"),
    ("ipympl", "ipympl"),          # backend for "%matplotlib widget"
    ("ipywidgets", "ipywidgets"),
    ("requests", "requests"),
    ("natsort", "natsort"),
]


def ensure_requirements(extra=None, quiet=True):
    """Install any missing requirements into the current kernel.

    Returns the list of package names that had to be installed (empty if
    everything was already present).
    """
    packages = list(_REQUIRED) + list(extra or [])
    missing = []
    for import_name, pip_name in packages:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        cmd = [sys.executable, "-m", "pip", "install"]
        if quiet:
            cmd.append("-q")
        cmd.extend(missing)
        subprocess.run(cmd, check=False)

    return missing

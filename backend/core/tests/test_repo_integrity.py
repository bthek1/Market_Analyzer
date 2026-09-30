import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SH = REPO_ROOT / "infra" / "deploy.sh"


def test_deploy_sh_exists():
    assert DEPLOY_SH.exists(), f"deploy.sh not found at {DEPLOY_SH}"


def test_deploy_sh_executable_on_disk():
    assert os.access(DEPLOY_SH, os.X_OK), (
        f"{DEPLOY_SH} is not executable — run: chmod +x infra/deploy.sh"
    )


def test_deploy_sh_executable_in_git():
    result = subprocess.run(
        ["git", "ls-files", "--stage", "infra/deploy.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    mode = result.stdout.split()[0]
    assert mode == "100755", (
        f"deploy.sh git mode is {mode}, expected 100755 — run: "
        "git update-index --chmod=+x infra/deploy.sh"
    )

import subprocess
from pathlib import Path


def test_shell_scripts_parse():
    root = Path(__file__).parents[1]
    for script in ["scripts/setup-statusline.sh", "scripts/gen-deploy-key.sh"]:
        result = subprocess.run(["bash", "-n", str(root / script)], check=False)
        assert result.returncode == 0

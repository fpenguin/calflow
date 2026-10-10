from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    tools = tmp_path / "bin"
    tools.mkdir()
    scripts = {
        "git": '''#!/bin/bash
if [ "$1" = "clone" ]; then mkdir -p "$3/.git"; touch "$3/requirements.txt"; exit 0; fi
if [ "$3" = "rev-parse" ]; then exit 0; fi
if [ "$3" = "status" ]; then printf '%s' "$DIRTY"; exit 0; fi
exit 1
''',
        "python3": '''#!/bin/bash
[ "$FAIL_SETUP" != "1" ] || exit 9
mkdir -p "$3/bin"
printf '#!/bin/bash\\nexit 0\\n' > "$3/bin/python"
chmod +x "$3/bin/python"
''',
        "launchctl": "#!/bin/bash\nexit 1\n",
    }
    for name, contents in scripts.items():
        path = tools / name
        path.write_text(contents)
        path.chmod(0o755)
    env = {**os.environ, "HOME": str(root), "PATH": str(tools) + ":/usr/bin:/bin",
           "DIRTY": "", "FAIL_SETUP": "0", "CALFLOW_REPO": "local-fixture"}
    installed = root / ".calflow"
    for directory in [".git", "data", "secrets"]:
        (installed / directory).mkdir(parents=True)
    (installed / "data" / "my_recipes.json").write_text('{"example":true}')
    (installed / "secrets" / "fixture.txt").write_text("synthetic-fixture")
    (installed / "old-code.txt").write_text("old")
    return root, installed, env


def test_upgrade_preserves_private_files_and_backup(home):
    # v1.5.6 - reinstall must not delete credentials or saved playbooks.
    root, installed, env = home
    result = subprocess.run(["bash", str(INSTALLER)], input="y\n", env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (installed / "data" / "my_recipes.json").read_text() == '{"example":true}'
    assert (installed / "secrets" / "fixture.txt").read_text() == "synthetic-fixture"
    assert list(root.glob(".calflow.backup.*/install/old-code.txt"))


def test_failed_upgrade_restores_previous_installation(home):
    root, installed, env = home
    env["FAIL_SETUP"] = "1"
    result = subprocess.run(["bash", str(INSTALLER)], input="y\n", env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert (installed / "old-code.txt").read_text() == "old"
    assert (installed / "secrets" / "fixture.txt").read_text() == "synthetic-fixture"


def test_upgrade_refuses_to_overwrite_tracked_local_changes(home):
    _, installed, env = home
    env["DIRTY"] = " M config/settings.py"
    result = subprocess.run(["bash", str(INSTALLER)], input="y\n", env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert (installed / "old-code.txt").exists()

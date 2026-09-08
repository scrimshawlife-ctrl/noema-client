"""Exercise the published shell recipe without installing packages in unit tests."""
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure", ["none", "venv", "pip", "pytest"])
def test_verification_recipe_is_private_and_cleans_up(tmp_path, failure):
    text = (ROOT / "SKILL_PROVENANCE.md").read_text()
    match = re.search(r"```bash\n(.*?)\n```", text, re.S)
    assert match is not None, "Verification recipe missing"
    recipe = match.group(1)
    assert "mktemp -d" in recipe
    assert "/tmp/noema-skill-check" not in recipe
    subprocess.run(["bash", "-n"], input=recipe, text=True, check=True)

    temp_root = tmp_path / "temporary files"
    temp_root.mkdir()
    sentinel = temp_root / "unrelated"
    sentinel.write_text("preserve")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Substitute only the expensive Python boundary; real bash/mktemp/traps/rm run.
    python = bin_dir / "python3"
    python.write_text('''#!/bin/bash
set -eu
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    test -d "$3"
    test "$(stat -c %a "$3")" = 700
    printf '%s\\n' "$3" >> "$RECIPE_LOG"
    [ "$RECIPE_FAILURE" != venv ] || exit 17
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
else
    printf '%s\\n' "$*" >> "$RECIPE_LOG"
    [ "$2" != "$RECIPE_FAILURE" ] || exit 17
fi
''')
    python.chmod(0o755)
    log = tmp_path / "calls"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               TMPDIR=str(temp_root), RECIPE_LOG=str(log), RECIPE_FAILURE=failure)
    for _ in range(2):
        result = subprocess.run(["bash", "-c", recipe], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        assert result.returncode == (0 if failure == "none" else 17), result.stderr
        assert list(temp_root.iterdir()) == [sentinel]
        assert sentinel.read_text() == "preserve"
    lines = log.read_text().splitlines()
    allocated = [line for line in lines if line.startswith(str(temp_root))]
    assert len(allocated) == 2
    assert allocated[0] != allocated[1]
    if failure == "none":
        assert lines.count("-m pip install . pytest") == 2
        assert lines.count("-m pytest -q") == 2
    elif failure == "pip":
        assert "-m pytest -q" not in lines

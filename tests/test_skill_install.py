import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]

import pytest

@pytest.mark.parametrize("component", ["skills", "profile", "leaf", "dotdot"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_symlink_redirect_is_refused(tmp_path, component, dry_run):
    profile = tmp_path / "home/profile"
    other = tmp_path / "home/other"
    other.mkdir(parents=True)
    (other / "sentinel").write_text("keep")
    if component == "profile":
        profile.symlink_to(other, target_is_directory=True)
    else:
        profile.mkdir()
        if component == "skills":
            (profile / "skills").symlink_to(other, target_is_directory=True)
        else:
            (profile / "skills").mkdir()
            (profile / "skills" / 'noema').symlink_to(other, target_is_directory=True)
    env = dict(os.environ, HOME=str(tmp_path / "home"), HERMES_HOME=str(profile))
    command = [sys.executable, str(ROOT / "scripts/install_skill.py")]
    if component == "dotdot":
        command += ["--target", str(profile / "skills" / 'noema' / ".." / "redirected")]
    result = subprocess.run(command + (["--dry-run"] if dry_run else []),
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout
    assert "symlink" in result.stderr.lower(), result.stderr
    assert (other / "sentinel").read_text() == "keep"
    assert sorted(p.name for p in other.iterdir()) == ["sentinel"]


def test_profile_install(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path / "home"), HERMES_HOME=str(tmp_path / "profile"))
    command = ['python3', str(ROOT / 'scripts/install_skill.py')]
    result = subprocess.run(command + ["--dry-run"], cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "profile").exists()
    assert not (tmp_path / "home").exists()
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    dest = tmp_path / "profile/skills/noema"
    assert (dest / "SKILL.md").read_text().startswith("---\n")
    for source in (ROOT / "skills/noema").rglob("*"):
        if source.is_file():
            assert (dest / source.relative_to(ROOT / "skills/noema")).read_bytes() == source.read_bytes()
    assert not (tmp_path / "home").exists()

def test_existing_directory_is_preserved(tmp_path):
    dest = tmp_path / "profile/skills/noema"
    dest.mkdir(parents=True)
    (dest / "sentinel").write_text("keep")
    result = subprocess.run(['python3', str(ROOT / 'scripts/install_skill.py')],
        env=dict(os.environ, HOME=str(tmp_path / "home"), HERMES_HOME=str(tmp_path / "profile")),
        capture_output=True)
    assert result.returncode != 0
    assert (dest / "sentinel").read_text() == "keep"

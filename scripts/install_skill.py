"""Install the source-checkout skill separately from the Python client."""
import argparse
import os
from pathlib import Path
import shutil
import stat
import tempfile


def reject_symlinks(path):
    """Check lexical components before resolve can hide a redirect (including /../)."""
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    for component in (*reversed(path.parents), path):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(f"refusing symlink path component: {component}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    parser.add_argument("--target", type=Path, default=home / "skills/noema")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "skills/noema"
    reject_symlinks(args.target)
    target = args.target.expanduser().resolve()
    if target == source or target in source.parents or source in target.parents:
        parser.error("source and target must not overlap")
    if args.target.is_symlink() or target.exists():
        parser.error("target exists; review and move it outside skills before upgrading")
    for name in ("SKILL.md", "references/protocol.md", "references/security.md", "references/troubleshooting.md"):
        if not (source / name).is_file():
            parser.error(f"incomplete source checkout: {name}")
    print(f"Install {source} -> {target}")
    if args.dry_run:
        return
    reject_symlinks(args.target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".noema-stage-", dir=target.parent) as tmp:
        stage = Path(tmp) / "noema"
        shutil.copytree(source, stage)
        reject_symlinks(args.target)
        stage.rename(target)
    print("Skill installed; restart Hermes and inspect skill_view(name='noema').")


if __name__ == "__main__":
    main()

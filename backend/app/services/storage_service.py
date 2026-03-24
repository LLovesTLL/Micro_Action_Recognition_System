from __future__ import annotations

from pathlib import Path


def cleanup_storage_dirs(*dirs: Path) -> dict[str, int]:
    """Delete temporary files under given directories.

    This project is currently single-user local demo oriented, so full cleanup is safe.
    """
    deleted_files = 0
    deleted_dirs = 0

    for root in dirs:
        if not root.exists() or not root.is_dir():
            continue

        for file_path in root.rglob("*"):
            if file_path.is_file():
                try:
                    file_path.unlink(missing_ok=True)
                    deleted_files += 1
                except OSError:
                    # Best-effort cleanup: ignore files currently in use.
                    pass

        child_dirs = sorted(
            [p for p in root.rglob("*") if p.is_dir()],
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for dir_path in child_dirs:
            try:
                dir_path.rmdir()
                deleted_dirs += 1
            except OSError:
                pass

    return {"deleted_files": deleted_files, "deleted_dirs": deleted_dirs}

"""Java sources selected by the Android network vault Gradle source set."""
import hashlib
import re
from pathlib import Path


def production_java_hashes(source_dir: Path) -> dict[str, str]:
    manifest = source_dir / "android-production-sources.txt"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Missing or symlinked Android network source list")
    names = manifest.read_text(encoding="utf-8").splitlines()
    if not names or len(names) != len(set(names)):
        raise ValueError("Android network source list is empty or contains duplicates")
    result = {}
    for name in names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.java", name):
            raise ValueError("Invalid Android network source filename")
        path = source_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or symlinked Android network source: {name}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

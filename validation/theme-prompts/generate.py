#!/usr/bin/env python3
"""Capture two real prompt engines; never read a user's shell configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unicodedata

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "sources.json").read_text())
SGR = re.compile(r"\x1b\[[0-9;]*m")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_file(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Pinned SHA256 mismatch: {path}")


def validate(raw):
    """Reject controls; calculate zero-based cursor with fixed wide CJK cells."""
    if len(raw) > 4096:
        raise ValueError("Prompt exceeds 4096 UTF-8 bytes")
    ansi = raw.decode("utf-8", errors="strict")
    visible = SGR.sub("", ansi)
    column = row = 0
    i = 0
    while i < len(visible):
        char = visible[i]
        if visible.startswith("\r\n", i):
            row += 1
            column = 0
            i += 2
            continue
        if unicodedata.category(char) in ("Cc", "Cf", "Cs"):
            raise ValueError(f"Control outside printable+SGR+CRLF: U+{ord(char):04X}")
        if not unicodedata.combining(char):
            column += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if column >= 40 or row >= 3:
            raise ValueError("Unexpected wrapping or out-of-bounds cursor")
        i += 1
    if row >= 3:
        raise ValueError("Too many CRLFs")
    return ansi, column, row


def capture(archive, posh, zsh):
    with tempfile.TemporaryDirectory(prefix="herdr-theme-prompts-v1-") as name:
        root = Path(name)
        home = root / "home"
        work = root / "work" / "中文"
        home.mkdir()
        work.mkdir(parents=True)
        # Only extract the checked official archive; reject traversal and links.
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise ValueError("Unsafe source archive member")
            source.extractall(root / "source")
        env = {
            "HOME": str(home), "ZDOTDIR": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "USER": "fixture", "LOGNAME": "fixture", "SHELL": str(zsh),
            "PATH": "/usr/bin:/bin", "LC_ALL": "en_US.UTF-8",
            "TERM": "xterm-256color", "COLUMNS": "40", "LINES": "3",
        }
        commands = [
            ("powerlevel10k", "Powerlevel10k 1.20.0 · 中文目录", [
                str(zsh), "-dfi", str(HERE / "render-p10k.zsh"),
                str(root / "source" / "powerlevel10k-1.20.0")]),
            ("oh-my-posh", "Oh My Posh 31.9.1 · 中文目录", [
                str(posh), "print", "primary", "--config", str(HERE / "posh.omp.json"),
                "--shell", "uni", "--escape=false", "--terminal-width", "40", "--status", "0"]),
        ]
        samples = []
        for ident, label, command in commands:
            result = subprocess.run(command, cwd=work, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=True, timeout=30)
            if result.stderr:
                raise ValueError(f"Unexpected stderr from {ident}: {result.stderr!r}")
            ansi, column, row = validate(result.stdout)
            samples.append(dict(id=ident, label=label, ansi=ansi,
                                cursorColumn=column, cursorRow=row))
        return dict(schemaVersion=1, id="theme-prompt-samples-v1", columns=40, rows=3,
                    samples=samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p10k-archive", type=Path, required=True)
    parser.add_argument("--oh-my-posh", type=Path, default=Path("/opt/homebrew/bin/oh-my-posh"))
    parser.add_argument("--zsh", type=Path, default=Path("/bin/zsh"))
    parser.add_argument("--output", type=Path, default=HERE.parent / "shared/theme-prompt-samples-v1.json")
    parser.add_argument("--check", action="store_true", help="Compare; do not overwrite fixture")
    args = parser.parse_args()
    checked_file(args.p10k_archive, LOCK["powerlevel10k"]["archiveSha256"])
    checked_file(args.oh_my_posh, LOCK["ohMyPosh"]["binarySha256"])
    checked_file(args.zsh, LOCK["zsh"]["binarySha256"])
    first = capture(args.p10k_archive.resolve(), args.oh_my_posh.resolve(), args.zsh.resolve())
    second = capture(args.p10k_archive.resolve(), args.oh_my_posh.resolve(), args.zsh.resolve())
    if first != second:
        raise ValueError("Independent clean-environment captures differ")
    serialized = json.dumps(first, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if args.output.read_text() != serialized:
            raise ValueError("Fixture differs from repeated real-engine output")
    else:
        args.output.write_text(serialized)
    print(json.dumps({"repeatedCaptureEqual": True, "fixtureSha256": hashlib.sha256(
        serialized.encode()).hexdigest(), "cursors": {
            sample["id"]: [sample["cursorColumn"], sample["cursorRow"]]
            for sample in first["samples"]}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check the actual Debian package without installing it or user fonts."""
from pathlib import Path
import subprocess
import sys


def valid_dependencies(value):
    groups = [set(part.strip().split(' (', 1)[0] for part in group.split('|'))
              for group in value.split(',')]
    return (any('libwebkit2gtk-4.1-0' in group for group in groups) and
            any('libgtk-3-0' in group for group in groups) and
            any({'fonts-noto-cjk', 'fonts-wqy-microhei'} <= group for group in groups))


def main(args):
    if len(args) != 1 or not Path(args[0]).is_file():
        raise SystemExit('expected exactly one built Debian package')
    result = subprocess.run(['dpkg-deb', '-f', args[0], 'Depends'], check=True,
                            capture_output=True, text=True, timeout=30)
    if not valid_dependencies(result.stdout):
        raise SystemExit('Debian package is missing GTK/WebKit or CJK font dependencies')
    print('Debian package retains GTK/WebKit and CJK font dependencies.')


if __name__ == '__main__':
    main(sys.argv[1:])

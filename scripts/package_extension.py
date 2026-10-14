#!/usr/bin/env python3
"""Package the standalone extension with its manifest at the ZIP root."""
import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('manifest.json', 'background.js', 'panel.html', 'panel.js', 'panel.css',
         'extractor.js', 'content.js', 'reply-format.js', 'theme.css')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / 'extension' / name, name)
    with zipfile.ZipFile(args.out) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(FILES):
            raise SystemExit('Extension ZIP validation failed')
        manifest = json.loads(archive.read('manifest.json'))
        print(f'Validated extension {manifest["version_name"]}: {args.out}')


if __name__ == '__main__':
    main()

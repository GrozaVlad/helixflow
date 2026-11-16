"""Export editable draw.io sources without resetting manual diagram edits.

Requires draw.io Desktop on PATH or --drawio /path/to/drawio. Works from
artifacts/ in the software repository and paper/ in the manuscript repository.
"""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drawio', default='drawio')
    parser.add_argument('--formats', nargs='+', choices=['pdf', 'svg', 'png'], default=['pdf', 'svg', 'png'])
    args = parser.parse_args()
    executable = shutil.which(args.drawio)
    if executable is None:
        parser.error('Install draw.io Desktop or pass --drawio /path/to/drawio. Overleaf uses the supplied PDFs directly.')
    base = Path(__file__).resolve().parent
    directory = base / ('diagrams' if (base/'diagrams').is_dir() else 'figures')
    exports = [('general_architecture', 'general_architecture', 1),
               ('local_execution', 'local_execution', 1),
               ('aws_infrastructure', 'aws_execution', 1),
               ('aws_infrastructure', 'aws_operations', 2)]
    for source, output, page in exports:
        for fmt in args.formats:
            subprocess.run([executable, '--export', '--format', fmt, '--crop',
                '--page-index', str(page), '--output', str(directory/f'{output}.{fmt}'),
                str(directory/f'{source}.drawio')], check=True)
    print(f'Exported draw.io architecture assets to {directory}')


if __name__ == '__main__':
    main()

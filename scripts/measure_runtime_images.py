#!/usr/bin/env python3
"""Compare local images and count shared uncompressed filesystem layers once."""
import argparse
import json
import re
import subprocess


def layer_sizes(image, inspected):
    output = subprocess.check_output(['docker', 'image', 'history', '--human=false', '--no-trunc',
                                      '--format', '{{json .}}', image]).decode()
    history = [json.loads(line) for line in output.splitlines()]
    # Metadata-only history records have no RootFS layer. WORKDIR may create an
    # empty directory (zero payload bytes) but still produces a filesystem layer.
    filesystem = [int(row['Size']) for row in reversed(history)
                  if int(row['Size']) > 0 or re.search(r'(?:^|#\(nop\)\s+)WORKDIR\s', row['CreatedBy'])]
    digests = inspected['RootFS']['Layers']
    if len(filesystem) != len(digests) or sum(filesystem) != inspected['Size']:
        raise RuntimeError('Image history cannot be mapped exactly to RootFS layers; refusing an estimated total')
    return dict(zip(digests, filesystem, strict=True))


def measure(images, layers=False):
    inspected = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *images]))
    result = {'images': {name: {'bytes': item['Size'], 'mib': round(item['Size'] / 1024**2, 2),
                                'id': item['Id']} for name, item in zip(images, inspected, strict=True)}}
    if layers:
        unique = {}
        for name, item in zip(images, inspected, strict=True):
            for digest, size in layer_sizes(name, item).items():
                if digest in unique and unique[digest] != size:
                    raise RuntimeError('Shared layer sizes disagree')
                unique[digest] = size
        total = sum(unique.values())
        result['shared_logical_layers'] = {'bytes': total, 'mib': round(total / 1024**2, 2),
            'layer_count': len(unique),
            'meaning': 'Uncompressed Docker logical layers, each RootFS digest counted once; not physical disk, RAM or registry download size'}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+')
    parser.add_argument('--layers', action='store_true')
    args = parser.parse_args()
    print(json.dumps(measure(args.images, args.layers), indent=2))

"""Inspect every layer of a docker-save archive, not only the final filesystem."""
import json
import sys
import tarfile
from pathlib import PurePosixPath

with tarfile.open(sys.argv[1]) as archive:
    manifests = json.load(archive.extractfile('manifest.json'))
    layers = {layer for manifest in manifests for layer in manifest['Layers']}
    findings = set()
    for layer in layers:
        with tarfile.open(fileobj=archive.extractfile(layer)) as files:
            for member in files:
                path = PurePosixPath(member.name.lstrip('./'))
                if not member.isfile() or not path.parts or path.parts[0] != 'app':
                    continue
                name = path.name.lower()
                if (name.startswith('.env') or '.git' in path.parts or 'secrets' in path.parts
                        or name.endswith(('.key', '.pem', '.crt', '.p12', '.pfx', '.jks', '.keystore', '.bak', '.backup', '.before-android-ip'))):
                    findings.add(str(path))
    print('layers_checked:', len(layers))
    print('sensitive_paths:', sorted(findings))
    if findings:
        sys.exit(1)

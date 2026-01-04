import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from api.c2pa.routes import _load_signing_credentials
pk, cc = _load_signing_credentials()
print('Loaded credentials')
print(f'Cert chain has {cc.count("BEGIN CERTIFICATE")} certificates')
print('This configuration should work!')

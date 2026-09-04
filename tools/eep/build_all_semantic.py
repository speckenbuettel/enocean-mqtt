import subprocess
import sys

TOOLS = [
    'tools/eep/export_semantic_role_mapping.py',
    'tools/eep/build_semantic_role_registry.py',
]

for tool in TOOLS:
    subprocess.run([sys.executable, tool], check=True)

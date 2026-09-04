from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SOURCE = Path('eep/semantic-role-mapping.json')
TARGET = Path('eep/semantic-role-registry.json')


def main() -> None:
    rows = json.loads(SOURCE.read_text(encoding='utf-8'))

    registry: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {'capabilities': set(), 'channel_types': set()}
    )

    for row in rows:
        role = row.get('semantic_role', '')
        if not role or role == 'TBD':
            continue

        capability = row.get('capability', '')
        channel_type = row.get('channel_type', '')

        if capability:
            registry[role]['capabilities'].add(capability)

        if channel_type:
            registry[role]['channel_types'].add(channel_type)

    result = []

    for role in sorted(registry):
        result.append(
            {
                'semantic_role': role,
                'capabilities': sorted(registry[role]['capabilities']),
                'channel_types': sorted(registry[role]['channel_types']),
            }
        )

    TARGET.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()

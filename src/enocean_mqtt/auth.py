"""Offline first-admin setup and recovery, without starting the gateway."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import secrets
import stat
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def _runtime_guard() -> Iterator[None]:
    # The gateway's process lock is Linux-only and shared by the current OS user.
    if sys.platform != "win32":
        from enocean_mqtt.instance_lock import InstanceAlreadyRunningError, instance_lock

        try:
            with instance_lock():
                yield
        except InstanceAlreadyRunningError:
            raise ValueError(
                "Stop the gateway running as this OS user before continuing."
            ) from None
    else:
        yield


def _check_path(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Token file and parent directories must not be symbolic links.")
    if path.exists() and not path.is_file():
        raise ValueError("Token path must be a regular file.")
    if sys.platform != "win32":
        for item in (path.parent, path):
            if not item.exists():
                continue
            info = item.stat()
            if info.st_uid != os.getuid():
                raise ValueError("Run as the OS user who owns the token file and its directory.")
            if stat.S_IMODE(info.st_mode) & 0o022:
                raise ValueError("Token file and its directory must not be group/world writable.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys in token registry; repair before recovery.")
        result[key] = value
    return result


def _load_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError(
            "Invalid token registry; preserve it and repair its JSON before recovery."
        ) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("tokens"), list):
        raise ValueError("Invalid token registry: expected an object containing a tokens list.")
    names: set[str] = set()
    token_values: set[str] = set()
    for entry in payload["tokens"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid token registry entry.")
        name, token, roles = entry.get("name"), entry.get("token"), entry.get("roles")
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name in names:
            raise ValueError("Token names must be nonempty, unique and without surrounding spaces.")
        if (
            not isinstance(roles, list)
            or not roles
            or any(role not in ("read", "admin") for role in roles)
        ):
            raise ValueError("Every token must have read and/or admin roles.")
        try:
            valid = isinstance(token, str) and len(base64.b64decode(token, validate=True)) >= 32
        except (ValueError, binascii.Error):
            valid = False
        if not isinstance(token, str) or not valid or token in token_values:
            raise ValueError("Tokens must be unique Base64 values containing at least 32 bytes.")
        names.add(name)
        token_values.add(token)
    return payload


def provision_admin(path: Path, *, name: str, recover: bool = False) -> str:
    """Create or recover one admin; caller must stop the gateway/use its OS account."""
    if not name.strip() or name != name.strip() or any(ord(char) < 32 for char in name):
        raise ValueError("Choose a nonempty token name without control or surrounding whitespace.")
    # Do not resolve symlinks before checking them.
    path = path.absolute()
    _check_path(path)
    with _runtime_guard():
        if recover:
            payload = _load_registry(path)
        else:
            if path.exists():
                raise ValueError(
                    "Token registry already exists. Use recover; init never overwrites."
                )
            payload = {"tokens": []}
        entry = next((item for item in payload["tokens"] if item["name"] == name), None)
        if entry is not None and "admin" not in entry["roles"]:
            raise ValueError("This name belongs to a read-only token; choose a new admin name.")
        token = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        if entry is None:
            payload["tokens"].append({"name": name, "token": token, "roles": ["admin"]})
        else:
            entry["token"] = token
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _check_path(path)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".api-tokens-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if recover:
                os.replace(temporary, path)
            else:
                # Publish complete contents exclusively, never overwrite even in a race.
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return token


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "recover"))
    parser.add_argument("--name", required=True, help="Token name / Web UI username")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path("config/secrets/api-tokens.json"),
        help="Exact configured token file (relative to the current directory)",
    )
    args = parser.parse_args(argv)
    if not sys.stdout.isatty():
        print("Refusing to display a secret outside an interactive terminal.", file=sys.stderr)
        return 1
    try:
        token = provision_admin(args.token_file, name=args.name, recover=args.command == "recover")
    except (OSError, ValueError) as exc:
        # Never echo registry contents or an OS error containing file contents.
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else (
                "Cannot access/write the token registry. Check its path, permissions and existence."
            )
        )
        print(f"Authentication setup refused: {message}", file=sys.stderr)
        return 1
    print(
        "Admin token saved. Store this secret in your password manager; do not share this output."
    )
    print(f"Web UI username: {args.name}")
    print(f"Web UI password / API Bearer token: {token}")
    print(
        "Enable web_api.authentication.enabled in your configuration before starting the gateway."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

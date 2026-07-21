"""Merge the private KOL master list with public incremental account lists."""

from __future__ import annotations

from pathlib import Path

import yaml


def merged_accounts_file(base: str | Path, extra: str | Path, output: str | Path) -> Path:
    base_path, extra_path, output_path = Path(base), Path(extra), Path(output)
    base_payload = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    extra_payload = yaml.safe_load(extra_path.read_text(encoding="utf-8")) or {}
    accounts = list(base_payload.get("accounts") or [])
    seen = {str(item.get("handle") or "").lower() for item in accounts}
    for item in extra_payload.get("accounts") or []:
        handle = str(item.get("handle") or "").strip()
        if handle and handle.lower() not in seen:
            accounts.append(item)
            seen.add(handle.lower())
    output_path.write_text(
        yaml.safe_dump({"accounts": accounts}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return output_path

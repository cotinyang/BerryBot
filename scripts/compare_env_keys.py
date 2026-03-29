#!/usr/bin/env python3
"""Compare keys between an env file and its sample file.

Usage examples:
  python scripts/compare_env_keys.py --sample client/.env.example --env client/.env
  python scripts/compare_env_keys.py --sample server/.env.example --env server/.env
    python scripts/compare_env_keys.py --sample client/.env.example --env client/.env --fill-missing
    python scripts/compare_env_keys.py --sample client/.env.example --env client/.env --fill-missing --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TypedDict

ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


class SampleEntry(TypedDict):
    line: str
    commented: bool


def parse_env_keys(path: Path, include_commented: bool = False) -> set[str]:
    """Parse env-like file and return declared keys.

    Args:
        path: Env file path.
        include_commented: Whether lines like '# KEY=value' count as declared.
    """
    keys: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        candidate = raw_line
        if line.startswith("#"):
            if not include_commented:
                continue
            candidate = line[1:].lstrip()

        match = ENV_KEY_RE.match(candidate)
        if match:
            keys.add(match.group(1))
    return keys


def parse_sample_entries(path: Path) -> dict[str, SampleEntry]:
    """Parse sample file and map key -> assignment metadata.

    Commented assignment lines like '# KEY=value' are normalized to 'KEY=value',
    and their comment status is preserved.
    """
    entries: dict[str, SampleEntry] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        candidate = raw_line
        is_commented = False
        if stripped.startswith("#"):
            is_commented = True
            candidate = stripped[1:].lstrip()

        match = ENV_KEY_RE.match(candidate)
        if not match:
            continue

        key = match.group(1)
        # Keep the first declaration from sample to preserve author intent.
        entries.setdefault(
            key,
            {
                "line": candidate.strip(),
                "commented": is_commented,
            },
        )
    return entries


def append_missing_entries(
    env_path: Path,
    sample_entries: dict[str, SampleEntry],
    missing_keys: list[str],
) -> int:
    """Append missing keys into env file from sample entries.

    Returns number of entries appended.
    """
    lines_to_append = [sample_entries[key] for key in missing_keys if key in sample_entries]
    if not lines_to_append:
        return 0

    content = env_path.read_text(encoding="utf-8")
    if content and not content.endswith("\n"):
        content += "\n"

    content += "\n# Appended by compare_env_keys.py --fill-missing\n"
    content += "\n".join(lines_to_append)
    content += "\n"
    env_path.write_text(content, encoding="utf-8")
    return len(lines_to_append)


def build_missing_lines(
    sample_entries: dict[str, SampleEntry],
    missing_keys: list[str],
) -> list[str]:
    """Build normalized KEY=value lines for missing keys.

    Rules:
    - Skip entries that are commented in sample.
    - Skip entries with empty value (e.g. KEY=).
    """
    lines: list[str] = []
    for key in missing_keys:
        entry = sample_entries.get(key)
        if entry is None:
            continue
        if entry["commented"]:
            continue

        line = entry["line"]
        _lhs, _eq, rhs = line.partition("=")
        if rhs.strip() == "":
            continue

        lines.append(line)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare env keys between .env and .env.example",
    )
    parser.add_argument(
        "--sample",
        default=".env.example",
        help="Path to sample env file (default: .env.example)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to current env file (default: .env)",
    )
    parser.add_argument(
        "--fill-missing",
        action="store_true",
        help="Append missing keys into env file using values from sample",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what --fill-missing would append without writing files",
    )
    args = parser.parse_args(argv)

    sample_path = Path(args.sample)
    env_path = Path(args.env)

    if not sample_path.exists():
        print(f"Error: sample file not found: {sample_path}")
        return 2
    if not env_path.exists():
        print(f"Error: env file not found: {env_path}")
        return 2
    if args.dry_run and not args.fill_missing:
        print("Error: --dry-run requires --fill-missing")
        return 2

    # Sample should include commented template keys by default.
    sample_keys = parse_env_keys(sample_path, include_commented=True)
    sample_entries = parse_sample_entries(sample_path)
    # Env should only include actively configured keys.
    env_keys = parse_env_keys(env_path, include_commented=False)

    missing_in_env = sorted(sample_keys - env_keys)
    extra_in_env = sorted(env_keys - sample_keys)

    print(f"Sample: {sample_path}")
    print(f"Env:    {env_path}")
    print(f"Sample keys: {len(sample_keys)}")
    print(f"Env keys:    {len(env_keys)}")
    print()

    if missing_in_env:
        print(f"Missing in env ({len(missing_in_env)}):")
        for key in missing_in_env:
            print(f"  - {key}")
        print()
    else:
        print("Missing in env: none")
        print()

    if extra_in_env:
        print(f"Extra in env ({len(extra_in_env)}):")
        for key in extra_in_env:
            print(f"  + {key}")
        print()
    else:
        print("Extra in env: none")
        print()

    if not missing_in_env and not extra_in_env:
        print("Result: env and sample keys are aligned.")
        return 0

    if args.fill_missing and missing_in_env:
        lines_to_append = build_missing_lines(sample_entries, missing_in_env)
        if args.dry_run:
            print("Dry run: would append the following lines to env:")
            if lines_to_append:
                for line in lines_to_append:
                    print(f"  {line}")
            else:
                print("  (none)")
            print(f"Dry run summary: {len(lines_to_append)} entries would be appended")
            return 1

        appended_count = append_missing_entries(env_path, sample_entries, missing_in_env)
        print(f"Filled missing keys into env: {appended_count}")
        # Re-evaluate after fill.
        env_keys = parse_env_keys(env_path, include_commented=False)
        missing_in_env = sorted(sample_keys - env_keys)
        extra_in_env = sorted(env_keys - sample_keys)
        if not missing_in_env:
            print("Result: missing keys filled. Env now covers all sample keys.")
            return 0

    print("Result: key differences found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Compare keys between an env file and its sample file.

Usage examples:
  python scripts/compare_env_keys.py --sample client/.env.example --env client/.env
  python scripts/compare_env_keys.py --sample server/.env.example --env server/.env
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


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
    args = parser.parse_args(argv)

    sample_path = Path(args.sample)
    env_path = Path(args.env)

    if not sample_path.exists():
        print(f"Error: sample file not found: {sample_path}")
        return 2
    if not env_path.exists():
        print(f"Error: env file not found: {env_path}")
        return 2

    # Sample should include commented template keys by default.
    sample_keys = parse_env_keys(sample_path, include_commented=True)
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

    print("Result: key differences found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# =============================================================================
# Schwab Account Mapper
# Author: King Maws
# Description: Utility to discover and map Schwab account identifiers for
#              automated trading bot configuration. Maps account numbers,
#              display names, and hashes for multi-account setups.
# =============================================================================

# Dump Schwab account identifiers.
#
# Usage:
#   python dump_schwab_accounts.py [--write-config]
#
# The script reads config.json in the current working directory, uses the
# credentials under the "schwab" key to connect, and prints a convenient
# table mapping raw account numbers → hash → displayId.
#
# With the optional --write-config flag the script will automatically write
# these mappings into config.json under:
#
#   "schwab": {
#       "accounts": {
#          "<displayId>": "<hash>",
#          "<accountNumber>": "<hash>",
#          "<hash>": "<hash>"
#       }
#   }
#
# so that the trading bot can use them without a look-up every run.

import json
import os
import argparse
import logging
from pathlib import Path
from typing import Dict

from schwab_broker import SchwabBroker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Schwab account identifier map")
    parser.add_argument("--config", default="config.json", help="Path to config file (default: config.json)")
    parser.add_argument("--write-config", action="store_true", help="Persist mapping into config.json under schwab.accounts")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file {cfg_path} not found")

    with cfg_path.open("r") as f:
        cfg = json.load(f)

    schwab_cfg = cfg.get("schwab", {})
    broker = SchwabBroker(
        client_id=schwab_cfg.get("app_key"),
        client_secret=schwab_cfg.get("app_secret"),
        token_path=schwab_cfg.get("token_path"),
        redirect_uri=schwab_cfg.get("redirect_uri"),
    )

    print("\nAvailable Schwab accounts:")
    print("-------------------------------------------------------------")
    accounts: Dict[str, str] = {}
    for key in broker.list_accounts():
        acct_hash = broker._account_map[key]  # type: ignore[attr-defined]
        accounts[key] = acct_hash
        print(f"{key:20} -> {acct_hash}")

    if args.write_config:
        cfg.setdefault("schwab", {}).setdefault("accounts", {}).update(accounts)
        with cfg_path.open("w") as f:
            json.dump(cfg, f, indent=4)
        print(f"\nUpdated 'accounts' map written back to {cfg_path}")


if __name__ == "__main__":
    main() 
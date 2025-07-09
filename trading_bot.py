#!/usr/bin/env python3
# =============================================================================
# Multi-Exchange Trading Bot
# Author: King Maws
# Description: Advanced automated trading system supporting Robinhood and 
#              Charles Schwab brokerages with comprehensive order management,
#              risk controls, and detailed reporting capabilities.
# =============================================================================

# Standard library imports
import pandas as pd
import logging
import json
import os
import sys
import math
from datetime import datetime
from typing import Dict, List, Optional
import argparse
import time
import csv

# Third-party imports
# ADD_IMPORT_START
# Use higher-level wrapper that supports multiple Schwab accounts
from schwab_broker import SchwabBroker
# ADD_IMPORT_END

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import checks
try:
    import robin_stocks.robinhood as rh
    from robin_stocks.robinhood import profiles
    ROBINHOOD_AVAILABLE = True
except ImportError:
    ROBINHOOD_AVAILABLE = False
    print("Warning: robin_stocks not installed. Install with: pip install robin_stocks")

try:
    import schwab
    from schwab import auth, client
    SCHWAB_AVAILABLE = True
except ImportError:
    SCHWAB_AVAILABLE = False
    print("Warning: schwab-py not installed. Install with: pip install schwab-py")

# New location of equity order helpers (schwab-py >= 1.4)
try:
    from schwab.orders.equities import (
        equity_buy_market,
        equity_sell_market,
        equity_buy_limit,
        equity_sell_limit,
    )
except ImportError:
    # Fallback – helpers unavailable (older schwab-py); will reference via legacy path
    equity_buy_market = equity_sell_market = equity_buy_limit = equity_sell_limit = None

# New Schwab order helpers for building custom orders
try:
    from schwab.orders.generic import OrderBuilder
    from schwab.orders.common import Session, Duration, OrderType as SchwabOrderType, OrderStrategyType, EquityInstruction
except ImportError:
    # If schwab-py is too old these will not be available – fall back to None so we can guard later
    OrderBuilder = None  # type: ignore
    Session = Duration = SchwabOrderType = OrderStrategyType = EquityInstruction = None  # type: ignore

class TradingBot:
    def __init__(self, config_file: str = "config.json"):
        """Initialize the trading bot with configuration"""
        self.config = self.load_config(config_file)
        self.robinhood_client = None
        self.robinhood_account_number = None
        self.schwab_client = None
        # Will be resolved at Schwab initialisation time. Needed because users may supply either
        # an explicit account hash or just the Schwab "displayId" (e.g. "Rollover IRA").
        self.schwab_account_hash = None
        # Higher-level wrapper that can map multiple Schwab accounts
        self.schwab_broker: Optional[SchwabBroker] = None
        self.trade_results = []
        
    def load_config(self, config_file: str) -> Dict:
        """Load configuration from JSON file"""
        default_config = {
            "robinhood": {
                "username": "",
                "password": "",
                "mfa_code": None
            },
            "schwab": {
                "app_key": "",
                "app_secret": "",
                "redirect_uri": "https://127.0.0.1:8182",
                "token_path": "./schwab_tokens.json",
                "account_hash": "",
                "account_name": "",
                "account_by_ticker": {},
                "enable_proactive_refresh": True,
                "refresh_threshold_days": 5
            },
            "trading": {
                "dry_run": True,
                "max_order_value": 10000.0,
                "default_time_in_force": "DAY",
                "results_dir": "trade_results",
                "limit_order_timeout": 30,  # seconds (max 60)
                "csv_log_file": "order_log.csv"
            }
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                logger.info(f"Loaded configuration from {config_file}")
                return {**default_config, **config}
            except Exception as e:
                logger.error(f"Error loading config file: {e}")
                return default_config
        else:
            # Create default config file
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Created default configuration file: {config_file}")
            return default_config
    
    def initialize_robinhood(self) -> bool:
        """Initialize Robinhood connection"""
        if not ROBINHOOD_AVAILABLE:
            logger.error("Robinhood API not available. Install robin_stocks package.")
            return False
            
        try:
            username = self.config["robinhood"]["username"]
            password = self.config["robinhood"]["password"]
            mfa_code = self.config["robinhood"]["mfa_code"]
            
            if not username or not password:
                logger.error("Robinhood credentials not configured")
                return False
                
            login_result = rh.login(username, password, mfa_code=mfa_code)
            if login_result.get('access_token'):
                logger.info("Successfully logged into Robinhood")
                self.robinhood_client = rh
                
                # Get account number right after login
                try:
                    acct_resp = profiles.load_account_profile(info="account_number")
                    # The call can give back a string or a list (first element is the acct-number)
                    if isinstance(acct_resp, list):
                        acct_resp = acct_resp[0] if acct_resp else None

                    self.robinhood_account_number = acct_resp

                    if self.robinhood_account_number:
                        logger.info(
                            f"Retrieved Robinhood account number: {self.robinhood_account_number}"
                        )
                    else:
                        logger.warning("Could not retrieve account number")
                except Exception as e:
                    logger.error(f"Error getting account number: {e}")
                    return False
                
                return True
            else:
                logger.error("Failed to login to Robinhood")
                return False
                
        except Exception as e:
            logger.error(f"Error initializing Robinhood: {e}")
            return False
    
    def initialize_schwab(self) -> bool:
        """Initialize Schwab connection (now via SchwabBroker for multi-account support)"""
        if not SCHWAB_AVAILABLE:
            logger.error("Schwab API not available. Install schwab-py package.")
            return False

        # The SchwabBroker class encapsulates token-file handling and account look-ups
        try:
            # Patch SchwabBroker's module-level credentials dynamically so
            # existing deployments that rely on *config.json* continue to
            # work.  (SchwabBroker normally pulls these from
            # environment.instance_settings.)
            import schwab_broker as _sb_mod  # local alias

            _sb_mod.client_id = self.config["schwab"].get("app_key", _sb_mod.client_id)
            _sb_mod.client_secret = self.config["schwab"].get("app_secret", _sb_mod.client_secret)
            _sb_mod.redirect_uri = self.config["schwab"].get("redirect_uri", _sb_mod.redirect_uri)
            _sb_mod.token_path = self.config["schwab"].get("token_path", _sb_mod.token_path)

            # Initialize SchwabBroker with enhanced token management settings
            enable_proactive_refresh = self.config["schwab"].get("enable_proactive_refresh", True)
            refresh_threshold_days = self.config["schwab"].get("refresh_threshold_days", 5)
            
            self.schwab_broker = _sb_mod.SchwabBroker(
                enable_proactive_refresh=enable_proactive_refresh,
                refresh_threshold_days=refresh_threshold_days
            )

            # Expose the raw Schwab client under the old attribute so that any
            # helper functions which still rely on it (e.g. polling for order
            # status) continue to work without large refactors.
            self.schwab_client = self.schwab_broker._schwab_client  # type: ignore[attr-defined]

            # Cache the account map and log available identifiers for
            # convenience/debugging.
            available_accounts = self.schwab_broker.list_accounts()
            logger.info("SchwabBroker initialised – available accounts: %s", available_accounts)

            # Maintain backwards-compatibility by picking a *default* account
            # (hash) using the same logic the old implementation used. This is
            # only a fallback; per-trade account selection happens later.
            cfg_hash = self.config["schwab"].get("account_hash")
            cfg_name = self.config["schwab"].get("account_name")

            if cfg_hash:
                # Provided hash – trust directly
                self.schwab_account_hash = cfg_hash
            elif cfg_name:
                self.schwab_account_hash = self._lookup_schwab_hash(cfg_name)
            elif available_accounts:
                # Fallback to first account returned by API
                self.schwab_account_hash = self.schwab_broker._account_map.get(available_accounts[0])  # type: ignore[attr-defined]

            logger.info("Default Schwab account hash set to: %s", self.schwab_account_hash)
            return True

        except Exception as e:
            logger.error(f"Error initialising SchwabBroker: {e}")
            return False
    
    def read_csv_file(self, csv_file: str) -> pd.DataFrame:
        """Read and validate CSV file with trade instructions"""
        try:
            df = pd.read_csv(csv_file, header=None, names=[
                'exchange', 'ticker', 'action', 'order_type', 'quantity', 'price', 'session'
            ], comment='#', skip_blank_lines=True)
            logger.info(f"Read {len(df)} trades from {csv_file}")

            # Default values / cleaning
            df['exchange'] = df['exchange'].str.strip().str.lower()
            df['ticker'] = df['ticker'].str.strip().str.upper()
            df['action'] = df['action'].str.strip().str.lower()
            df['order_type'] = df['order_type'].str.strip().str.lower()
            df['session'] = df['session'].fillna('normal').str.strip().str.lower()

            # Validate required columns (implicitly ensured by names list)
            # Validate exchanges
            valid_exchanges = ['hood', 'sch', 'shh', 'schwab']
            invalid_exchanges = df[~df['exchange'].isin(valid_exchanges)]['exchange'].unique()
            if len(invalid_exchanges) > 0:
                raise ValueError(f"Invalid exchange values: {invalid_exchanges}")

            # Validate actions
            valid_actions = ['buy', 'sell']
            invalid_actions = df[~df['action'].isin(valid_actions)]['action'].unique()
            if len(invalid_actions) > 0:
                raise ValueError(f"Invalid action values: {invalid_actions}")

            # Validate order types
            # Adding support for a convenience 'last' order type (extended-hours limit at last traded price)
            valid_order_types = ['market', 'limit', 'last']
            invalid_order_types = df[~df['order_type'].isin(valid_order_types)]['order_type'].unique()
            if len(invalid_order_types) > 0:
                raise ValueError(f"Invalid order_type values: {invalid_order_types}")

            # Validate sessions
            valid_sessions = ['normal', 'ext', '24']
            invalid_sessions = df[~df['session'].isin(valid_sessions)]['session'].unique()
            if len(invalid_sessions) > 0:
                raise ValueError(f"Invalid session values: {invalid_sessions}")

            # Ensure price present for limit orders
            for idx, row in df[df['order_type'] == 'limit'].iterrows():
                if pd.isna(row['price']):
                    raise ValueError(f"Price missing for limit order at line {idx+1}")

            # Default session to 'ext' for 'last' orders if the user didn't specify otherwise
            df.loc[(df['order_type'] == 'last') & (df['session'] == 'normal'), 'session'] = 'ext'

            # Clean quantity field but preserve dollar amounts - convert to string first
            df['quantity'] = df['quantity'].astype(str).str.strip()

            # Validate quantity field - can be integer or dollar amount (for market buys only)
            for idx, row in df.iterrows():
                qty_str = str(row['quantity'])
                if qty_str.startswith('$'):
                    # Dollar amount - validate it's a valid float and only for market buys
                    if row['action'] != 'buy' or row['order_type'] != 'market':
                        raise ValueError(f"Dollar amounts (${qty_str}) are only allowed for market buy orders at line {idx+1}")
                    try:
                        dollar_amount = float(qty_str[1:])
                        if dollar_amount <= 0:
                            raise ValueError(f"Dollar amount must be positive at line {idx+1}")
                    except ValueError:
                        raise ValueError(f"Invalid dollar amount '{qty_str}' at line {idx+1}")
                else:
                    # Regular quantity - must be positive integer
                    try:
                        qty_int = int(qty_str)
                        if qty_int <= 0:
                            raise ValueError(f"Quantity must be positive integer at line {idx+1}")
                    except ValueError:
                        raise ValueError(f"Invalid quantity '{qty_str}' at line {idx+1}")

            # Price to float (quantity stays as string to preserve dollar amounts)
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            return df

        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise
    
    def _convert_dollar_amount_to_shares(self, ticker: str, dollar_amount: float, exchange: str) -> int:
        """Convert dollar amount to number of shares, rounded up to next whole number"""
        try:
            if exchange == 'Hood':
                if not self.robinhood_client:
                    raise ValueError("Robinhood not initialized")
                current_price = float(self.robinhood_client.get_latest_price(ticker)[0])
            else:  # Schwab
                if not self.schwab_broker:
                    raise ValueError("Schwab not initialized")
                quote_json = self.schwab_broker.get_quote(ticker)
                current_price = quote_json[ticker]['quote']['lastPrice']
            
            # Calculate shares and round up to next whole number
            shares = dollar_amount / current_price
            shares_rounded = math.ceil(shares)
            
            logger.info(f"Converting ${dollar_amount} to {shares_rounded} shares of {ticker} at ${current_price:.2f} per share")
            return shares_rounded
            
        except Exception as e:
            logger.error(f"Error converting dollar amount to shares: {e}")
            raise
    
    def _log_to_csv(self, result: Dict):
        """Append result to CSV log file with timestamp"""
        log_file = self.config.get("trading", {}).get("csv_log_file", "order_log.csv")
        fieldnames = ['timestamp', 'exchange', 'ticker', 'action', 'order_type', 'quantity', 'price', 'session', 'status', 'message', 'order_id']
        # Ensure file exists with header
        file_exists = os.path.isfile(log_file)
        try:
            with open(log_file, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({k: result.get(k, '') for k in fieldnames})
        except Exception as e:
            logger.error(f"Error writing to CSV log: {e}")
    
    def _robinhood_wait_for_fill_or_timeout(self, order_id: str, timeout: int) -> (bool, str):
        """Wait until order is filled or timeout (seconds). Returns tuple(success, state)"""
        start = time.time()
        while time.time() - start < timeout:
            info = self.robinhood_client.get_stock_order_info(order_id)
            state = info.get('state', '') if info else ''
            if state == 'filled':
                return True, 'filled'
            if state in ['cancelled', 'rejected', 'failed']:
                return False, state
            time.sleep(3)
        # timeout - attempt cancel
        try:
            self.robinhood_client.cancel_stock_order(order_id)
            return False, 'cancelled_timeout'
        except Exception:
            return False, 'timeout_no_cancel'
    
    def _schwab_wait_for_fill_or_timeout(self, account_hash: str, order_id: str, timeout: int) -> (bool, str):
        """Poll Schwab order status until filled or timeout. Returns tuple(success, state)"""
        start = time.time()
        poll_interval = 3  # seconds
        while time.time() - start < timeout:
            try:
                resp = self.schwab_client.get_order(order_id, account_hash)
                if resp.status_code != 200:
                    # If API temporarily fails, keep trying until timeout
                    time.sleep(poll_interval)
                    continue

                data = resp.json()
                state = data.get('status', '').upper()

                if state == 'FILLED':
                    return True, 'filled'
                if state in ['CANCELED', 'EXPIRED', 'REJECTED']:
                    return False, state.lower()
            except Exception:
                # Swallow exceptions during polling and keep trying
                pass

            time.sleep(poll_interval)

        # Timeout reached
        return False, 'timeout'
    
    def _resolve_time_in_force(self, order_type: str = 'limit') -> str:
        """Return a valid Robinhood timeInForce string (gfd or gtc).

        Robinhood accepts only two codes:
        • gfd – Good for day  (maps from DAY, GFD, etc.)
        • gtc – Good till cancel

        Market orders are not allowed to have GTC, so if the user has
        configured GTC but the current order is a market order we fall
        back to GFD automatically to avoid the 'invalid good till
        canceled' API error.
        """
        raw_value = str(self.config.get('trading', {}).get('default_time_in_force', 'DAY')).lower()

        mapping = {
            'day': 'gfd', 'gfd': 'gfd',
            'gtc': 'gtc', 'good_till_cancel': 'gtc',
            'good_till_cancelled': 'gtc', 'good_till_canceled': 'gtc',
        }

        tif = mapping.get(raw_value, 'gfd')
        # Market orders cannot be GTC on Robinhood
        if order_type == 'market' and tif == 'gtc':
            tif = 'gfd'
        return tif
    
    def execute_robinhood_trade(self, ticker: str, action: str, order_type: str, quantity: int, price: float, session: str) -> Dict:
        """Execute a trade on Robinhood"""
        result = {
            'exchange': 'Robinhood',
            'ticker': ticker,
            'action': action,
            'order_type': order_type,
            'quantity': quantity,
            'price': price,
            'session': session,
            'status': 'failed',
            'message': '',
            'order_id': None,
            'timestamp': datetime.now().isoformat()
        }
        try:
            if self.config["trading"]["dry_run"]:
                result['status'] = 'success'
                result['message'] = 'DRY RUN - Trade not executed'
                result['order_id'] = 'dry_run_' + str(int(time.time()))
                logger.info(f"DRY RUN: {action.upper()} {quantity} shares of {ticker} on Robinhood ({order_type})")
                return result

            if not self.robinhood_account_number:
                result['message'] = "No account number available"
                return result

            # Determine the effective price and estimated order value
            if order_type == 'last':
                # Fetch the most recent trade price
                price = float(self.robinhood_client.get_latest_price(ticker)[0])
                estimated_value = price * quantity
            elif order_type == 'limit' and price is not None:
                estimated_value = price * quantity
            else:  # market order – look up current quote for risk check
                quote = self.robinhood_client.get_latest_price(ticker)[0]
                estimated_value = float(quote) * quantity

            if estimated_value > self.config["trading"]["max_order_value"]:
                result['message'] = f"Order value ${estimated_value:.2f} exceeds maximum ${self.config['trading']['max_order_value']}"
                return result

            # 'last' orders are always placed in extended hours by design
            extended_hours = (order_type == 'last') or (session in ['ext', '24'])

            if order_type == 'market':
                if action == 'buy':
                    order = self.robinhood_client.order_buy_market(
                        ticker,
                        quantity,
                        timeInForce=self._resolve_time_in_force('market'),
                        account_number=self.robinhood_account_number,
                        extendedHours=extended_hours,
                    )
                else:
                    order = self.robinhood_client.order_sell_market(
                        ticker,
                        quantity,
                        timeInForce=self._resolve_time_in_force('market'),
                        account_number=self.robinhood_account_number,
                        extendedHours=extended_hours,
                    )
            elif order_type in ['limit', 'last']:
                if price is None:
                    result['message'] = "Price required for limit/last order"
                    return result
                if action == 'buy':
                    order = self.robinhood_client.order_buy_limit(
                        ticker,
                        quantity,
                        price,
                        timeInForce=self._resolve_time_in_force('limit'),
                        extendedHours=extended_hours,
                        account_number=self.robinhood_account_number,
                    )
                else:
                    order = self.robinhood_client.order_sell_limit(
                        ticker,
                        quantity,
                        price,
                        timeInForce=self._resolve_time_in_force('limit'),
                        extendedHours=extended_hours,
                        account_number=self.robinhood_account_number,
                    )
            else:
                result['message'] = f"Unsupported order type: {order_type}"
                return result

            if order and order.get('id'):
                result['order_id'] = order['id']
                if order_type == 'limit':
                    timeout = min(int(self.config['trading'].get('limit_order_timeout', 30)), 60)
                    success, state = self._robinhood_wait_for_fill_or_timeout(order['id'], timeout)
                    if success:
                        result['status'] = 'success'
                        result['message'] = f'Limit order filled ({state})'
                    else:
                        result['status'] = 'failed'
                        result['message'] = f'Limit order not filled ({state})'
                else:
                    result['status'] = 'success'
                    result['message'] = f"Market order placed successfully. State: {order.get('state', 'unknown')}"
                logger.info(f"Robinhood {order_type.upper()} {action.upper()} {quantity} {ticker} - Order ID: {result['order_id']}")
            else:
                result['message'] = f"Order failed: {order}"
        except Exception as e:
            result['message'] = f"Error executing trade: {str(e)}"
            logger.error(f"Robinhood trade error: {e}")
        return result
    
    def execute_schwab_trade(self, ticker: str, action: str, order_type: str, quantity: int, price: float, session: str) -> Dict:
        """Execute a trade on Schwab"""
        result = {
            'exchange': 'Schwab',
            'ticker': ticker,
            'action': action,
            'order_type': order_type,
            'quantity': quantity,
            'price': price,
            'session': session,
            'status': 'failed',
            'message': '',
            'order_id': None,
            'timestamp': datetime.now().isoformat()
        }
        try:
            if self.config["trading"]["dry_run"]:
                result['status'] = 'success'
                result['message'] = 'DRY RUN - Trade not executed'
                result['order_id'] = 'dry_run_' + str(int(time.time()))
                logger.info(f"DRY RUN: {action.upper()} {quantity} shares of {ticker} on Schwab ({order_type})")
                return result

            # Determine which Schwab account this trade should use
            acct_map = self.config.get("schwab", {}).get("account_by_ticker", {})
            selected_account: str | None = acct_map.get(ticker)

            # Fall back to the defaults configured earlier (hash or name)
            if not selected_account:
                selected_account = (
                    self.config["schwab"].get("account_hash")
                    or self.config["schwab"].get("account_name")
                    or None
                )

            if not selected_account:
                result["message"] = "No Schwab account identifier configured for this trade"
                return result

            # --- Quote retrieval using SchwabBroker (JSON already)
            try:
                quote_json = self.schwab_broker.get_quote(ticker)
                current_price = quote_json[ticker]['quote']['lastPrice']
            except Exception as quote_err:
                result['message'] = f"Failed to get quote for {ticker}: {quote_err}"
                return result

            # For 'last' orders we want to use the most recent traded price as the effective limit
            if order_type == 'last':
                price = current_price
            # Recalculate order value for risk check (same logic as before)
            estimated_value = (price if order_type in ['limit', 'last'] and price else current_price) * quantity
            if estimated_value > self.config['trading']['max_order_value']:
                result['message'] = (
                    f"Order value ${estimated_value:.2f} exceeds maximum ${self.config['trading']['max_order_value']}"
                )
                return result

            # Resolve to the real account *hash* via the broker's account map –
            # this is needed for the order-status polling helper.
            account_hash = self._lookup_schwab_hash(selected_account)
            if not account_hash:
                result['message'] = f"Could not resolve hash for account {selected_account!r}"
                return result

            # Decide whether this order should be routed to the extended-hours
            # session.  Our convenience *last* type always uses EXT, otherwise
            # it depends on the user-supplied session column.
            is_extended = (order_type == 'last') or (session in ['ext', '24'])

            # Build using the high-level helpers shipped with schwab-py. Newer
            # releases return an *OrderBuilder* instance while older versions
            # return a simple *dict*.  We treat both uniformly and only attempt
            # to override the *session* field if the helper produced a *dict*.
            if order_type == 'market':
                if equity_buy_market and equity_sell_market:
                    order_spec = (
                        equity_buy_market(ticker, quantity)
                        if action == 'buy'
                        else equity_sell_market(ticker, quantity)
                    )
                else:
                    # Legacy fallback for older schwab-py versions
                    order_spec = schwab.orders.equity_buy_market(ticker, quantity) if action == 'buy' else schwab.orders.equity_sell_market(ticker, quantity)

                # For market orders the *session* field can be overridden only when the
                # helper returns a *dict*.  Newer versions of schwab-py return a fully
                # built ``dict`` so modifying it is safe.  If the helper now returns an
                # ``OrderBuilder`` instance we leave it untouched because extended-hours
                # market orders are not currently supported by the Schwab API.
                if is_extended and isinstance(order_spec, dict):
                    order_spec['session'] = 'EQUITY_EXTENDED'

            elif order_type in ['limit', 'last']:
                if price is None:
                    result['message'] = "Price required for limit/last order"
                    return result

                if equity_buy_limit and equity_sell_limit:
                    order_spec = (
                        equity_buy_limit(ticker, quantity, price)
                        if action == 'buy'
                        else equity_sell_limit(ticker, quantity, price)
                    )
                else:
                    order_spec = (
                        schwab.orders.equity_buy_limit(ticker, quantity, price)
                        if action == 'buy'
                        else schwab.orders.equity_sell_limit(ticker, quantity, price)
                    )

                # For our convenience 'last' orders (or any limit order the user
                # explicitly flags as extended) we need to flip the session.  Only
                # attempt the override when the helper returned a *dict* to avoid
                # the previously seen "object does not support item assignment"
                # error with *OrderBuilder* objects.
                if is_extended and isinstance(order_spec, dict):
                    order_spec['session'] = 'EQUITY_EXTENDED'
            else:
                result['message'] = f"Unsupported order type: {order_type}"
                return result

            # Place the order *via* SchwabBroker so callers can pass fuzzy ids
            try:
                order_id = self.schwab_broker.place_order(order_spec, selected_account)
            except Exception as place_err:
                result['message'] = f"Order failed: {place_err}"
                return result

            if order_id:
                result['order_id'] = order_id
                if order_type == 'limit':
                    timeout = min(int(self.config['trading'].get('limit_order_timeout', 30)), 60)
                    success, state = self._schwab_wait_for_fill_or_timeout(account_hash, result['order_id'], timeout)
                    if success:
                        result['status'] = 'success'
                        result['message'] = f'Limit order filled ({state})'
                    else:
                        result['status'] = 'failed'
                        result['message'] = f'Limit order not filled ({state})'
                else:
                    result['status'] = 'success'
                    result['message'] = 'Market order submitted'
                logger.info(f"Schwab {order_type.upper()} {action.upper()} {quantity} {ticker} - Order ID: {result['order_id']}")
            else:
                result['message'] = "Order failed – no order-id returned"
        except Exception as e:
            result['message'] = f"Error executing trade: {str(e)}"
            logger.error(f"Schwab trade error: {e}")
        return result
    
    def execute_trades(self, csv_file: str) -> List[Dict]:
        """Execute all trades from CSV file"""
        try:
            trades_df = self.read_csv_file(csv_file)
            results = []
            
            for index, trade in trades_df.iterrows():
                exchange_raw = trade['exchange']
                exchange = 'Hood' if exchange_raw in ['hood'] else 'Schwab'
                ticker = trade['ticker']
                action = trade['action']
                order_type = trade['order_type']
                quantity_str = str(trade['quantity'])
                price = trade['price'] if not pd.isna(trade['price']) else None
                session = trade['session']

                # Convert dollar amount to shares if needed
                if quantity_str.startswith('$'):
                    dollar_amount = float(quantity_str[1:])
                    try:
                        # Initialize the appropriate client first
                        if exchange == 'Hood' and self.robinhood_client is None:
                            if not self.initialize_robinhood():
                                raise ValueError("Could not initialize Robinhood")
                        elif exchange == 'Schwab' and self.schwab_client is None:
                            if not self.initialize_schwab():
                                raise ValueError("Could not initialize Schwab")
                        
                        quantity = self._convert_dollar_amount_to_shares(ticker, dollar_amount, exchange)
                        logger.info(f"Converted ${dollar_amount} to {quantity} shares of {ticker}")
                    except Exception as e:
                        result = {
                            'exchange': exchange, 'ticker': ticker, 'action': action, 'order_type': order_type,
                            'quantity': quantity_str, 'price': price, 'session': session, 'status': 'failed',
                            'message': f'Error converting ${dollar_amount} to shares: {e}', 'order_id': None, 
                            'timestamp': datetime.now().isoformat()
                        }
                        results.append(result)
                        self._log_to_csv(result)
                        print(f"FAIL {exchange} {ticker}: {result['message']}")
                        continue
                else:
                    quantity = int(quantity_str)

                logger.info(f"Processing trade {index + 1}/{len(trades_df)}: {action.upper()} {quantity} {ticker} on {exchange} ({order_type})")

                if exchange == 'Hood':
                    if self.robinhood_client is None and not self.initialize_robinhood():
                        result = {
                            'exchange': 'Robinhood', 'ticker': ticker, 'action': action, 'order_type': order_type,
                            'quantity': quantity, 'price': price, 'session': session, 'status': 'failed',
                            'message': 'Robinhood not initialized', 'order_id': None, 'timestamp': datetime.now().isoformat()
                        }
                        results.append(result)
                        self._log_to_csv(result)
                        print(f"FAIL Robinhood {ticker}: {result['message']}")
                        continue
                    result = self.execute_robinhood_trade(ticker, action, order_type, quantity, price, session)
                else:  # Schwab
                    if self.schwab_client is None and not self.initialize_schwab():
                        result = {
                            'exchange': 'Schwab', 'ticker': ticker, 'action': action, 'order_type': order_type,
                            'quantity': quantity, 'price': price, 'session': session, 'status': 'failed',
                            'message': 'Schwab not initialized', 'order_id': None, 'timestamp': datetime.now().isoformat()
                        }
                        results.append(result)
                        self._log_to_csv(result)
                        print(f"FAIL Schwab {ticker}: {result['message']}")
                        continue
                    result = self.execute_schwab_trade(ticker, action, order_type, quantity, price, session)

                results.append(result)
                self.trade_results.append(result)
                self._log_to_csv(result)

                status_icon = "PASS" if result['status'] == 'success' else "FAIL"
                print(f"{status_icon} {result['exchange']} {ticker} {action.upper()} ({order_type}) - {result['message']}")

                time.sleep(1)  # Sequential processing delay
            
            print("\nNOTE: All orders were processed sequentially. Parallel execution is possible with threading or asyncio but is not implemented to ensure predictable sequencing and API rate-limit safety.")
            
            return results
            
        except Exception as e:
            logger.error(f"Error executing trades: {e}")
            raise
    
    def save_results(self, results: List[Dict], output_file: str = None) -> str:
        """Save trade results to file"""
        # Determine target directory from config (fallback to "trade_results")
        results_dir = self.config.get("trading", {}).get("results_dir", "trade_results")
        os.makedirs(results_dir, exist_ok=True)

        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"trade_results_{timestamp}.json"

        # If the caller passed just a filename, place it inside results_dir
        if not os.path.isabs(output_file):
            output_path = os.path.join(results_dir, output_file)
        else:
            # Absolute/relative path provided explicitly; honour as is
            output_path = output_file
        
        try:
            with open(output_path, 'w') as f:
                json.dump(results, f, indent=4)
            
            logger.info(f"Results saved to {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            raise
    
    def print_summary(self, results: List[Dict]):
        """Print summary of trade results"""
        total_trades = len(results)
        successful_trades = len([r for r in results if r['status'] == 'success'])
        failed_trades = total_trades - successful_trades
        
        print("\n" + "="*50)
        print("TRADE EXECUTION SUMMARY")
        print("="*50)
        print(f"Total Trades: {total_trades}")
        print(f"Successful: {successful_trades}")
        print(f"Failed: {failed_trades}")
        print(f"Success Rate: {(successful_trades/total_trades)*100:.1f}%" if total_trades > 0 else "Success Rate: 0%")
        
        print("\nDETAILED RESULTS:")
        print("-"*50)
        for i, result in enumerate(results, 1):
            status_icon = "PASS" if result['status'] == 'success' else "FAIL"
            print(f"{i:2d}. {status_icon} {result['exchange']:10} {result['action'].upper():4} {result['quantity']:4} {result['ticker']:6} - {result['message']}")
        
        print("="*50)

    def _lookup_schwab_hash(self, identifier: str) -> Optional[str]:
        """Return the account *hash* for any fuzzy identifier (number, name, hash).

        Uses SchwabBroker's cached map and performs a case-insensitive
        fallback match if an exact key is not present.  Returns ``None`` if
        the identifier cannot be resolved or the broker is not initialised.
        """
        if not self.schwab_broker or not identifier:
            return None

        # Exact key first
        h = self.schwab_broker._account_map.get(str(identifier))  # type: ignore[attr-defined]
        if h:
            return h

        # Case-insensitive scan of keys
        ident_lower = str(identifier).lower()
        for key, val in self.schwab_broker._account_map.items():  # type: ignore[attr-defined]
            if str(key).lower() == ident_lower:
                return val
        return None

    def list_schwab_accounts(self):
        """Print a table of available Schwab account identifiers and their hashes.

        This is a convenience helper so users can copy-paste the correct
        identifier (number, display name, or hash) into *config.json* or the
        CSV file.  It initialises the Schwab connection if necessary and then
        prints all identifiers that map to each unique account hash.
        """
        if self.schwab_client is None:
            # Lazily initialise Schwab (suppresses output if already done)
            if not self.initialize_schwab():
                print("Unable to initialise Schwab – cannot list accounts.")
                return

        # At this point the broker must exist and its account-map populated
        acct_map = getattr(self.schwab_broker, "_account_map", None)  # type: ignore[attr-defined]
        if not acct_map:
            print("No Schwab accounts found (account map is empty).")
            return

        # Build a reverse map: hash → list[identifier]
        reverse: Dict[str, List[str]] = {}
        for key, h in acct_map.items():
            # Skip the redundant self-mapping (hash → hash) when encountered
            if key == h:
                continue
            reverse.setdefault(h, []).append(key)

        print("\nAVAILABLE SCHWAB ACCOUNTS")
        print("=" * 80)
        print(f"{'ACCOUNT HASH':<36} | OTHER IDENTIFIERS (number / display name)")
        print("-" * 80)
        for h, keys in reverse.items():
            print(f"{h:<36} | {', '.join(sorted(keys))}")
        print("=" * 80)

    def check_schwab_token_status(self) -> Dict:
        """Check Schwab token status and return detailed information"""
        if not self.schwab_broker:
            return {"error": "Schwab broker not initialized"}
        
        try:
            status = self.schwab_broker.get_token_status()
            
            # Add interpretation and recommendations
            if status.get("status") == "expired":
                status["recommendation"] = "Token has expired. Run the bot to trigger automatic re-authentication."
            elif status.get("needs_refresh", False):
                status["recommendation"] = f"Token is {status.get('age_days', 0)} days old. Consider running the bot to trigger proactive refresh."
            elif status.get("status") == "valid":
                status["recommendation"] = "Token is healthy and fresh."
            elif status.get("status") == "no_token_file":
                status["recommendation"] = "No token file found. Run the bot to perform initial authentication."
            else:
                status["recommendation"] = "Token status unclear. Check configuration and try running the bot."
            
            return status
            
        except Exception as e:
            logger.error(f"Error checking token status: {e}")
            return {"error": f"Failed to check token status: {e}"}

def create_sample_csv():
    """Create a sample CSV file with example trades"""
    sample_data = [
        {'exchange': 'hood', 'ticker': 'AAPL', 'action': 'buy', 'order_type': 'market', 'quantity': 10, 'price': '', 'session': 'normal'},
        {'exchange': 'hood', 'ticker': 'MSFT', 'action': 'buy', 'order_type': 'market', 'quantity': '$500', 'price': '', 'session': 'normal'},
        {'exchange': 'sch', 'ticker': 'GOOGL', 'action': 'buy', 'order_type': 'market', 'quantity': '$1000', 'price': '', 'session': 'normal'},
        {'exchange': 'sch', 'ticker': 'TSLA', 'action': 'buy', 'order_type': 'limit', 'quantity': 5, 'price': 310.5, 'session': 'normal'},
        {'exchange': 'hood', 'ticker': 'NVDA', 'action': 'sell', 'order_type': 'market', 'quantity': 2, 'price': '', 'session': 'ext'},
    ]
    
    df = pd.DataFrame(sample_data)
    df.to_csv('sample_trades.csv', index=False)
    print("Created sample_trades.csv with example data (includes dollar amount examples)")

def main():
    """Main function for command line interface"""
    parser = argparse.ArgumentParser(description='Multi-Exchange Trading Bot')
    parser.add_argument('csv_file', nargs='?', help='CSV file with trade instructions')
    parser.add_argument('--config', default='config.json', help='Configuration file (default: config.json)')
    parser.add_argument('--output', help='Output file for results (default: auto-generated)')
    parser.add_argument('--dry-run', action='store_true', help='Perform dry run without executing trades')
    parser.add_argument('--create-sample', action='store_true', help='Create sample CSV file')
    parser.add_argument('--list-schwab-accounts', action='store_true', help='List Schwab account identifiers and hashes')
    parser.add_argument('--check-schwab-tokens', action='store_true', help='Check Schwab token status and expiration')
    
    args = parser.parse_args()
    
    if args.create_sample:
        create_sample_csv()
        return

    # List Schwab accounts (no CSV required)
    if args.list_schwab_accounts:
        bot = TradingBot(args.config)
        bot.list_schwab_accounts()
        return

    # Check Schwab token status (no CSV required)
    if args.check_schwab_tokens:
        bot = TradingBot(args.config)
        status = bot.check_schwab_token_status()
        
        print("\nSCHWAB TOKEN STATUS")
        print("=" * 50)
        
        if "error" in status:
            print(f"Error: {status['error']}")
        else:
            print(f"Status: {status.get('status', 'unknown').upper()}")
            if 'created' in status:
                print(f"Created: {status['created']}")
            if 'age_days' in status:
                print(f"Age: {status['age_days']} days")
            if 'days_until_refresh_expiry' in status:
                print(f"Days until refresh token expires: {status['days_until_refresh_expiry']}")
            if 'needs_refresh' in status:
                print(f"Needs refresh: {'YES' if status['needs_refresh'] else 'NO'}")
            if 'recommendation' in status:
                print(f"\nRecommendation: {status['recommendation']}")
        
        print("=" * 50)
        return

    if not args.csv_file:
        parser.print_help()
        return
    
    # Initialize trading bot
    bot = TradingBot(args.config)
    
    # Override dry run from command line
    if args.dry_run:
        bot.config["trading"]["dry_run"] = True
    
    try:
        # Execute trades
        results = bot.execute_trades(args.csv_file)
        
        # Save results
        output_file = bot.save_results(results, args.output)
        
        # Print summary
        bot.print_summary(results)
        
        print(f"\nDetailed results saved to: {output_file}")
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
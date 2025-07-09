# =============================================================================
# Schwab Broker Interface
# Author: King Maws
# Description: Enhanced wrapper for schwab-py API with multi-account support,
#              automatic token management, and robust error handling for
#              professional trading applications.
# =============================================================================

# Standard library imports
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Union, Optional

# Third-party imports
from schwab import auth
from schwab.orders.common import Duration, OrderStrategyType, Session, OrderType, EquityInstruction
from schwab.orders.generic import OrderBuilder

# -----------------------------------------------------------------------------
# Local settings (adjust the relative path if your project layout differs)
# -----------------------------------------------------------------------------
local_lib_dir = os.path.join(os.path.dirname(__file__), 'lib')
if local_lib_dir not in sys.path:
    sys.path.append(local_lib_dir)

try:
    from environment.instance_settings import schwabSettings
except ImportError:  # pragma: no cover – module is optional
    # Fall back to environment variables (or leave blank).  These will be
    # patched by *TradingBot.initialize_schwab* based on the user's
    # ``config.json`` settings, so it is safe to continue even if they are
    # empty here.
    client_id = os.getenv("SCHWAB_APP_ID", "")
    client_secret = os.getenv("SCHWAB_APP_SECRET", "")
    redirect_uri = os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1:8182")
    token_path = os.getenv("SCHWAB_TOKEN_PATH", "./schwab_tokens.json")

# If the caller already knows the hash they can skip look-up entirely
FuzzyAccount = Union[str, int]  # account number, display name, or hash

logger = logging.getLogger(__name__)


class SchwabBroker:
    # Thin wrapper around schwab-py that supports multiple accounts with enhanced token management.
    #
    # The broker keeps an account-id → hash map that is populated on first
    # request. Any of the following identifiers can be passed to place_order:
    #
    # * Raw account number ("12345678")
    # * Display name ("Rollover IRA")
    # * Account hash itself
    #
    # Enhanced Features:
    # * Automatic token expiration detection and refresh
    # * Graceful fallback authentication when tokens expire
    # * Proactive token refresh to prevent interruptions
    # * Comprehensive error recovery for authentication issues

    # ---------------------------------------------------------------------
    def __init__(self, enable_proactive_refresh: bool = True, refresh_threshold_days: int = 5) -> None:
        # Initialize Schwab broker with enhanced token management.
        #
        # Args:
        #   enable_proactive_refresh: If True, automatically refresh tokens before expiration
        #   refresh_threshold_days: Days before expiration to trigger proactive refresh (default: 5)
        logger.info("Initialising Schwab API client with enhanced token management...")
        
        self.enable_proactive_refresh = enable_proactive_refresh
        self.refresh_threshold_days = refresh_threshold_days
        self._broker_name: str = "Schwab"
        self._account_map: Dict[str, str] | None = None  # key → hash
        self._schwab_client = None
        
        # Initialize the client with token management
        self._initialize_client_with_fallback()

    def _initialize_client_with_fallback(self) -> None:
        # Initialize Schwab client with automatic fallback authentication on token issues.
        try:
            # First, check if token file exists and validate it
            if os.path.exists(token_path):
                token_status = self._validate_token_file()
                
                if token_status == "valid":
                    logger.info("Loading existing valid tokens...")
                    self._schwab_client = auth.client_from_token_file(
                        api_key=client_id,
                        app_secret=client_secret,
                        token_path=token_path,
                    )
                    logger.info("Successfully loaded existing tokens")
                    
                elif token_status == "expired":
                    logger.warning("Tokens are expired. Initiating re-authentication...")
                    self._perform_full_authentication()
                    
                elif token_status == "near_expiry":
                    logger.info("Loading tokens that are near expiry...")
                    try:
                        self._schwab_client = auth.client_from_token_file(
                            api_key=client_id,
                            app_secret=client_secret,
                            token_path=token_path,
                        )
                        logger.info("Successfully loaded near-expiry tokens")
                        
                        if self.enable_proactive_refresh:
                            logger.info("Scheduling proactive token refresh...")
                            self._perform_proactive_refresh()
                            
                    except Exception as e:
                        logger.warning(f"Failed to load near-expiry tokens: {e}. Re-authenticating...")
                        self._perform_full_authentication()
                        
                else:  # corrupted or invalid
                    logger.warning("Token file is corrupted or invalid. Re-authenticating...")
                    self._perform_full_authentication()
                    
            else:
                logger.info("No token file found. Initiating first-time authentication...")
                self._perform_full_authentication()
                
        except Exception as e:
            logger.error(f"Error during client initialization: {e}. Attempting full re-authentication...")
            self._perform_full_authentication()

    def _validate_token_file(self) -> str:
        # Validate token file and return status: 'valid', 'expired', 'near_expiry', or 'invalid'.
        try:
            with open(token_path, 'r') as f:
                token_data = json.load(f)
            
            # Check if required fields exist
            if 'creation_timestamp' not in token_data:
                logger.warning("Token file missing creation timestamp")
                return "invalid"
            
            # Calculate refresh token age (7-day expiration policy)
            creation_time = token_data['creation_timestamp']
            current_time = time.time()
            
            # Convert timestamps to readable format for logging
            creation_dt = datetime.fromtimestamp(creation_time)
            
            token_age_days = (current_time - creation_time) / (24 * 3600)
            days_until_refresh_expiry = 7.0 - token_age_days
            
            logger.info(f"Token analysis:")
            logger.info(f"  Created: {creation_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"  Age: {token_age_days:.1f} days")
            logger.info(f"  Days until refresh token expires: {days_until_refresh_expiry:.1f}")
            
            # Check refresh token expiration status (Schwab refresh tokens expire after 7 days)
            if token_age_days >= 7.0:
                logger.warning("Refresh token has expired (7+ days old)")
                return "expired"
            elif token_age_days >= self.refresh_threshold_days:
                logger.warning(f"Token is {token_age_days:.1f} days old (threshold: {self.refresh_threshold_days} days)")
                return "near_expiry"
            else:
                logger.info("Token is valid and fresh")
                return "valid"
                
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            logger.error(f"Error reading or parsing token file: {e}")
            return "invalid"
        except Exception as e:
            logger.error(f"Unexpected error validating token file: {e}")
            return "invalid"

    def _perform_full_authentication(self) -> None:
        # Perform full OAuth authentication flow.
        try:
            logger.info("Starting full OAuth authentication flow...")
            
            # Remove old token file if it exists
            if os.path.exists(token_path):
                backup_path = f"{token_path}.backup_{int(time.time())}"
                os.rename(token_path, backup_path)
                logger.info(f"Backed up old token file to {backup_path}")
            
            # Perform full authentication
            self._schwab_client = auth.easy_client(
                api_key=client_id,
                app_secret=client_secret,
                callback_url=redirect_uri,
                token_path=token_path,
            )
            
            logger.info("Full authentication completed successfully")
            
        except Exception as e:
            logger.error(f"Full authentication failed: {e}")
            raise RuntimeError(f"Failed to authenticate with Schwab API: {e}")

    def _perform_proactive_refresh(self) -> None:
        # Perform proactive token refresh before expiration.
        try:
            logger.info("Performing proactive token refresh...")
            
            # Create a new client which should trigger token refresh
            self._schwab_client = auth.client_from_token_file(
                api_key=client_id,
                app_secret=client_secret,
                token_path=token_path,
            )
            
            logger.info("Proactive token refresh completed")
            
        except Exception as e:
            logger.warning(f"Proactive refresh failed: {e}. Will attempt full re-authentication.")
            self._perform_full_authentication()

    def _handle_authentication_error(self, error: Exception, operation: str) -> None:
        # Handle authentication errors by attempting re-authentication.
        error_msg = str(error).lower()
        
        # Check if error is authentication-related
        if any(keyword in error_msg for keyword in ['token', 'auth', 'unauthorized', 'forbidden', '401', '403']):
            logger.warning(f"Authentication error during {operation}: {error}")
            logger.info("Attempting automatic re-authentication...")
            
            try:
                self._perform_full_authentication()
                logger.info("Re-authentication successful")
            except Exception as reauth_error:
                logger.error(f"Re-authentication failed: {reauth_error}")
                raise RuntimeError(f"Failed to recover from authentication error: {reauth_error}")
        else:
            # Not an authentication error, re-raise original
            raise error

    def get_token_status(self) -> Dict[str, any]:
        # Get current token status information.
        if not os.path.exists(token_path):
            return {"status": "no_token_file", "message": "No token file found"}
        
        try:
            with open(token_path, 'r') as f:
                token_data = json.load(f)
            
            creation_time = token_data.get('creation_timestamp', 0)
            current_time = time.time()
            
            token_age_days = (current_time - creation_time) / (24 * 3600)
            days_until_refresh_expiry = 7.0 - token_age_days
            
            # Refresh token expires after 7 days from creation
            is_expired = token_age_days >= 7.0
            status = "expired" if is_expired else "valid"
            
            return {
                "status": status,
                "created": datetime.fromtimestamp(creation_time).isoformat(),
                "age_days": round(token_age_days, 1),
                "days_until_refresh_expiry": round(days_until_refresh_expiry, 1),
                "needs_refresh": token_age_days >= self.refresh_threshold_days
            }
            
        except Exception as e:
            return {"status": "error", "message": f"Error reading token file: {e}"}

    # ---------------------------------------------------------------------
    def broker_name(self) -> str:
        return self._broker_name

    # ------------------------------------------------------------------
    def _ensure_account_numbers(self, force_refresh: bool = False) -> None:
        # Populate self._account_map if it is empty with enhanced error handling.
        if self._account_map is not None and not force_refresh:
            return

        logger.info("Fetching Schwab account list …")
        
        try:
            resp = self._schwab_client.get_account_numbers()
            logger.debug("Response status %s – body: %s", resp.status_code, resp.text)
            resp.raise_for_status()

            self._account_map = {}
            for acct in resp.json():
                account_number: str = str(acct["accountNumber"])
                display_id: str = acct.get("displayId", "")
                hash_value: str = acct["hashValue"]

                # Map each possible key to the hash for easy look-up later
                self._account_map[account_number] = hash_value
                if display_id:
                    self._account_map[display_id] = hash_value
                self._account_map[hash_value] = hash_value

            logger.info("Cached %d Schwab account(s)", len(self._account_map))
            
        except Exception as e:
            self._handle_authentication_error(e, "account list fetch")
            
            # Retry after re-authentication
            resp = self._schwab_client.get_account_numbers()
            resp.raise_for_status()
            
            self._account_map = {}
            for acct in resp.json():
                account_number: str = str(acct["accountNumber"])
                display_id: str = acct.get("displayId", "")
                hash_value: str = acct["hashValue"]

                self._account_map[account_number] = hash_value
                if display_id:
                    self._account_map[display_id] = hash_value
                self._account_map[hash_value] = hash_value

            logger.info("Cached %d Schwab account(s) after re-authentication", len(self._account_map))

    # ------------------------------------------------------------------
    def list_accounts(self) -> List[str]:
        # Return a list of keys the caller can use (numbers + names).
        self._ensure_account_numbers()
        return list(self._account_map.keys())

    # ------------------------------------------------------------------
    def get_quote(self, symbol: str):
        # Get quote with enhanced error handling.
        logger.info("Requesting quote for %s", symbol)
        
        try:
            resp = self._schwab_client.get_quote(symbol)
            logger.debug("Quote response %s – body: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()
            
        except Exception as e:
            self._handle_authentication_error(e, f"quote request for {symbol}")
            
            # Retry after re-authentication
            resp = self._schwab_client.get_quote(symbol)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    def place_order(self, order: OrderBuilder, account: FuzzyAccount) -> str | None:
        # Place order for account (can be number, name, or hash) with enhanced error handling.
        #
        # Returns the order-id (string) if the call succeeds, otherwise None.
        self._ensure_account_numbers()

        account_hash = self._account_map.get(str(account))
        if not account_hash:
            raise ValueError(f"Unknown Schwab account identifier: {account!r}")

        logger.info("Placing order on account %s (hash %s)", account, account_hash)
        
        try:
            resp = self._schwab_client.place_order(account_hash, order)
            logger.debug("place_order response %s – headers: %s", resp.status_code, resp.headers)
            resp.raise_for_status()

            # Location header looks like …/orders/<id>
            location = resp.headers.get("Location") or resp.headers.get("location")
            if location and location.endswith("/orders") is False:
                return location.split("/")[-1]
            return None
            
        except Exception as e:
            self._handle_authentication_error(e, f"order placement for account {account}")
            
            # Retry after re-authentication
            resp = self._schwab_client.place_order(account_hash, order)
            resp.raise_for_status()
            
            location = resp.headers.get("Location") or resp.headers.get("location")
            if location and location.endswith("/orders") is False:
                return location.split("/")[-1]
            return None


# -----------------------------------------------------------------------------
# T E S T I N G (only runs when executed directly)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    broker = SchwabBroker()
    
    # Show token status
    token_status = broker.get_token_status()
    print("Token Status:", json.dumps(token_status, indent=2))
    
    print("Available identifiers:", broker.list_accounts())

    symbol = "AAPL"
    print("Quote:", json.dumps(broker.get_quote(symbol), indent=2))

    # Example limit buy
    order_spec = (
        OrderBuilder()
        .set_order_strategy_type(OrderStrategyType.SINGLE)
        .set_session(Session.NORMAL)
        .set_duration(Duration.DAY)
        .set_order_type(OrderType.LIMIT)
        .set_price(150.0)
        .add_equity_leg(EquityInstruction.BUY, symbol, 1)
        .build()
    )

    # Pick *any* identifier returned by list_accounts()
    first_key = broker.list_accounts()[0]
    order_id = broker.place_order(order_spec, first_key)
    print("Placed order – id:", order_id)
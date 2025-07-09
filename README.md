# Multi-Exchange Trading Bot

**Author:** King Maws  
**Version:** 1.0.0  
**License:** MIT

## Overview

A robust automated trading system that seamlessly integrates with multiple brokerage platforms(robinhood and schwab). This advanced trading bot provides institutional-quality order management, risk controls, and comprehensive reporting capabilities for professional traders and algorithmic trading strategies.

## Key Features

### 🏛️ **Multi-Brokerage Support**
- **Robinhood Integration**: Full API support with advanced order types
- **Charles Schwab Integration**: Professional trading platform with institutional features
- **Unified Interface**: Single codebase managing multiple brokerage accounts

### 📊 **Advanced Order Management**
- **Market & Limit Orders**: Complete order type support with intelligent execution
- **Extended Hours Trading**: Pre-market and after-hours session support
- **Smart Order Routing**: Automatic exchange selection and optimization
- **Position Management**: Real-time portfolio tracking and risk assessment

### 🛡️ **Enterprise Risk Controls**
- **Configurable Order Limits**: Maximum order value protection
- **Dry Run Mode**: Safe testing environment for strategy validation
- **Account Validation**: Pre-trade compliance and balance verification
- **Timeout Management**: Automatic order cancellation for unfilled limit orders

### 📈 **Comprehensive Reporting**
- **Real-time Execution Logs**: Detailed trade execution monitoring
- **Performance Analytics**: Success rates and execution quality metrics
- **JSON Export**: Structured data for further analysis and backtesting
- **Audit Trail**: Complete transaction history with timestamps

## Technical Architecture

### Core Components

- **`trading_bot.py`**: Main trading engine with order execution logic
- **`schwab_broker.py`**: Enhanced Schwab API wrapper with multi-account support
- **Token Management**: Automatic authentication and session handling
- **Configuration System**: Flexible JSON-based parameter management

### Dependencies

```
pandas>=1.3.0       # Data manipulation and analysis
robin_stocks>=3.0.0 # Robinhood API integration
schwab-py>=0.5.0    # Charles Schwab API integration
```

## Quick Start

### 1. Installation

```bash
git clone https://github.com/yourusername/multi-exchange-trading-bot.git
cd multi-exchange-trading-bot
pip install -r requirements.txt
```

### 2. Configuration

1. **Copy and configure settings:**
   ```bash
   cp config.json config_local.json
   ```

2. **Add your API credentials to `config_local.json`:**
   ```json
   {
     "robinhood": {
       "username": "your_email@example.com",
       "password": "your_secure_password"
     },
     "schwab": {
       "app_key": "your_schwab_app_key",
       "app_secret": "your_schwab_secret",
       "redirect_uri": "https://127.0.0.1:8182"
     }
   }
   ```

3. **Configure trading parameters:**
   ```json
   {
     "trading": {
       "dry_run": true,
       "max_order_value": 10000.0,
       "limit_order_timeout": 30
     }
   }
   ```

### 3. First Run

```bash
# Generate sample trading data
python trading_bot.py --create-sample

# Execute dry run (recommended)
python trading_bot.py sample_trades.csv --dry-run

# Execute live trades (when ready)
python trading_bot.py your_trades.csv --config config_local.json
```

## Trading Data Format

The system accepts CSV files with the following structure:

```csv
exchange,ticker,action,order_type,quantity,price,session
schwab,AAPL,buy,market,100,,normal
robinhood,MSFT,sell,limit,50,350.00,extended
schwab,GOOGL,buy,limit,25,2800.00,normal
```

### Field Specifications

| Field | Values | Description |
|-------|--------|-------------|
| `exchange` | `sch`, `hood` | Target brokerage platform |
| `ticker` | `AAPL`, `MSFT`, etc. | Stock symbol |
| `action` | `buy`, `sell` | Order direction |
| `order_type` | `market`, `limit` | Execution method |
| `quantity` | Integer | Number of shares |
| `price` | Float | Limit price (required for limit orders) |
| `session` | `normal`, `ext`, `24` | Trading session |

## Advanced Features

### Token Management

The system includes sophisticated token management for seamless operation:

```bash
# Check token status
python check_schwab_tokens.py

# Map account identifiers
python dump_schwab_accounts.py --write-config
```

### Multi-Account Support

Configure multiple Schwab accounts for advanced portfolio management:

```json
{
  "schwab": {
    "accounts": {
      "Primary Trading": "account_hash_1",
      "401k Rollover": "account_hash_2"
    },
    "account_by_ticker": {
      "AAPL": "Primary Trading",
      "VOO": "401k Rollover"
    }
  }
}
```

### Risk Management

Built-in safeguards protect against common trading errors:

- **Order Value Limits**: Prevent oversized trades
- **Account Balance Validation**: Ensure sufficient funds
- **Symbol Verification**: Validate ticker symbols
- **Session Compatibility**: Match orders to appropriate trading sessions


## API Integration Details

### Robinhood
- OAuth2 authentication with MFA support
- Real-time order status monitoring
- Extended hours trading capabilities

### Charles Schwab
- Professional API with institutional features
- Multi-account management
- Advanced order types and routing


## Disclaimer

This software is provided for educational and informational purposes. You're obviously responsible for your own trades


---

**Professional Trading Solution by King Maws** 

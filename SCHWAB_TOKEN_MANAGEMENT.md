# Schwab Token Management Guide

## Overview

The trading bot now includes **enhanced Schwab token management** that automatically handles token expiration and refresh to prevent authentication errors. This eliminates the "Exception while authenticating refresh token authentication" error by implementing:

- ✅ **Automatic token expiration detection**
- ✅ **Graceful fallback authentication when tokens expire**
- ✅ **Proactive token refresh before expiration**
- ✅ **Comprehensive error recovery for authentication issues**
- ✅ **Token status monitoring and reporting**

## Key Features

### 1. Automatic Token Validation
The bot automatically checks token health on startup:
- Validates token file structure and contents
- Calculates token age and time until expiration
- Determines if tokens need refresh or re-authentication

### 2. Intelligent Authentication Flow
- **Valid tokens**: Loads existing tokens and continues normally
- **Near expiry tokens**: Loads tokens and triggers proactive refresh
- **Expired tokens**: Automatically initiates full re-authentication
- **Missing/corrupted tokens**: Performs first-time authentication

### 3. Proactive Token Refresh
- Automatically refreshes tokens before they expire (default: 5 days)
- Prevents interruptions during trading operations
- Configurable refresh threshold

### 4. Error Recovery
- Detects authentication errors during API calls
- Automatically re-authenticates and retries operations
- Graceful handling of network issues and temporary failures

### 5. Token Status Monitoring
- Real-time token status checking
- Detailed expiration information
- Recommendations for token maintenance

## Configuration

Add these new settings to your `config.json`:

```json
{
  "schwab": {
    "app_key": "your_app_key",
    "app_secret": "your_app_secret",
    "redirect_uri": "https://127.0.0.1:8182",
    "token_path": "./schwab_tokens.json",
    "account_hash": "",
    "account_name": "",
    "enable_proactive_refresh": true,
    "refresh_threshold_days": 5
  }
}
```

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `enable_proactive_refresh` | `true` | Enable automatic token refresh before expiration |
| `refresh_threshold_days` | `5` | Days before expiration to trigger proactive refresh |

## Usage

### Basic Operation
The enhanced token management works automatically. Simply run your bot as usual:

```bash
python trading_bot.py your_trades.csv
```

The bot will:
1. Check token status on startup
2. Handle any token issues automatically
3. Refresh tokens proactively if needed
4. Continue with trading operations

### Check Token Status
Monitor your token health anytime:

```bash
# Using the trading bot
python trading_bot.py --check-schwab-tokens

# Using the dedicated utility
python check_schwab_tokens.py
```

Example output:
```
✅ Token Status: VALID
📅 Created: 2024-01-15T10:30:00
⏰ Expires: 2024-01-22T10:30:00  
📅 Age: 3.2 days
⏰ Time until expiry: 98.5 hours
✅ Needs refresh: NO

💡 Recommendation: Token is healthy and fresh.
```

### Force Token Refresh
Trigger token refresh manually:

```bash
# Run a dry-run to trigger token validation and refresh
python trading_bot.py --dry-run sample_trades.csv
```

## Token Lifecycle

### Timeline
- **Day 0**: Fresh token created
- **Day 1-4**: Token valid and fresh
- **Day 5**: Proactive refresh triggered (if enabled)
- **Day 7**: Token expires (Schwab policy)

### Status Indicators
- **🆕 Fresh** (0-2 days): Token is new and healthy
- **📅 Valid** (2-5 days): Token is working normally  
- **⚠️ Near Expiry** (5-7 days): Proactive refresh recommended
- **❌ Expired** (7+ days): Re-authentication required

## Troubleshooting

### Common Issues

#### "Token has expired" Error
**Cause**: Token is older than 7 days
**Solution**: Run the bot - it will automatically re-authenticate

#### "Token file missing" Error
**Cause**: No token file exists
**Solution**: Run the bot for first-time authentication

#### "Authentication error during API call"
**Cause**: Token became invalid during operation
**Solution**: The bot automatically detects and handles this

### Recovery Steps

1. **Check token status**:
   ```bash
   python check_schwab_tokens.py
   ```

2. **Force re-authentication** (if needed):
   ```bash
   # Delete token file to force fresh authentication
   del schwab_tokens.json  # Windows
   rm schwab_tokens.json   # Linux/Mac
   
   # Run bot to trigger re-authentication
   python trading_bot.py --dry-run sample_trades.csv
   ```

3. **Verify configuration**:
   - Check `app_key` and `app_secret` in config.json
   - Verify `redirect_uri` matches your Schwab app settings
   - Ensure `token_path` is writable

### Log Analysis

The bot provides detailed logging for token operations:

```
INFO - Initialising Schwab API client with enhanced token management...
INFO - Token analysis:
INFO -   Created: 2024-01-15 10:30:00
INFO -   Expires: 2024-01-22 10:30:00
INFO -   Age: 3.2 days
INFO -   Time until expiry: 98.5 hours
INFO - Token is valid and fresh
INFO - Successfully loaded existing tokens
```

Look for these log messages to understand token status and operations.

## Best Practices

### Recommended Settings
- Keep `enable_proactive_refresh: true` for uninterrupted operation
- Use `refresh_threshold_days: 5` for optimal balance
- Monitor token status weekly with `check_schwab_tokens.py`

### Security
- Keep your `schwab_tokens.json` file secure and private
- Don't share token files between different environments
- Use different token files for development vs production

### Automation
- Set up automated token monitoring in production environments
- Consider running token status checks in your deployment scripts
- Use dry-runs to test token health before important trading sessions

## Migration from Old Version

The enhanced token management is **backwards compatible**. No changes needed:

1. Your existing `config.json` continues to work
2. Existing token files are automatically validated
3. All current functionality is preserved
4. New features are enabled by default

## Support

If you encounter issues:

1. Check token status: `python check_schwab_tokens.py`
2. Review bot logs for authentication messages
3. Verify Schwab app configuration
4. Try manual re-authentication if needed

The enhanced token management should eliminate most authentication issues and provide a seamless trading experience. 
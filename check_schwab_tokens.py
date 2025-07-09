#!/usr/bin/env python3
# =============================================================================
# Schwab Token Status Checker
# Author: King Maws
# Description: Utility script to validate and monitor Schwab API token health,
#              providing detailed status information and refresh recommendations.
# =============================================================================

# A utility script to check the status and health of Schwab API tokens.

import json
import sys
from trading_bot import TradingBot

def main():
    # Check Schwab token status and print detailed information
    print("Schwab Token Status Checker")
    print("=" * 50)
    
    try:
        # Initialize trading bot (this will trigger token validation)
        bot = TradingBot()
        
        # Get token status
        status = bot.check_schwab_token_status()
        
        if "error" in status:
            print(f"❌ Error: {status['error']}")
            sys.exit(1)
        
        # Print status information
        status_emoji = "✅" if status.get('status') == 'valid' else "⚠️" if status.get('status') == 'near_expiry' else "❌"
        print(f"{status_emoji} Token Status: {status.get('status', 'unknown').upper()}")
        
        if 'created' in status:
            print(f"📅 Created: {status['created']}")
        
        if 'expires' in status:
            print(f"⏰ Expires: {status['expires']}")
        
        if 'age_days' in status:
            age_days = status['age_days']
            age_emoji = "🆕" if age_days < 2 else "📅" if age_days < 5 else "⚠️"
            print(f"{age_emoji} Age: {age_days} days")
        
        if 'hours_until_expiry' in status:
            hours = status['hours_until_expiry']
            if hours > 0:
                hours_emoji = "⏰" if hours > 24 else "⚠️"
                print(f"{hours_emoji} Time until expiry: {hours:.1f} hours")
            else:
                print("❌ Token has already expired")
        
        if 'needs_refresh' in status:
            refresh_emoji = "⚠️" if status['needs_refresh'] else "✅"
            print(f"{refresh_emoji} Needs refresh: {'YES' if status['needs_refresh'] else 'NO'}")
        
        print()
        print("💡 Recommendation:")
        print(f"   {status.get('recommendation', 'Check configuration and try running the bot.')}")
        
        # Additional tips
        print()
        print("📋 Tips:")
        print("   • Schwab tokens expire every 7 days")
        print("   • The bot automatically refreshes tokens when they're 5+ days old")
        print("   • Run a dry-run trade to trigger token refresh: python trading_bot.py --dry-run sample_trades.csv")
        print("   • Check token status anytime with: python check_schwab_tokens.py")
        
    except Exception as e:
        print(f"❌ Error checking token status: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
"""
Polymarket Notification System
"""

import os
import json
import requests
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from config import Config

@dataclass
class Alert:
    level: str  # INFO, WARNING, CRITICAL
    title: str
    message: str
    data: Optional[dict] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        self.timestamp = self.timestamp or datetime.utcnow()


class Notifier:
    COLORS = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "CRITICAL": "\033[91m",
        "RESET": "\033[0m"
    }
    
    def __init__(self):
        self.history = []
        self.discord_url = Config.notification.discord_webhook_url
        self.telegram_token = Config.notification.telegram_bot_token
        self.telegram_chat = Config.notification.telegram_chat_id
    
    def send(self, alert: Alert):
        self.history.append(alert)
        
        # Console
        if Config.notification.enable_console:
            self._console(alert)
        
        # Discord
        if self.discord_url:
            self._discord(alert)
        
        # Telegram
        if self.telegram_token and self.telegram_chat:
            self._telegram(alert)
    
    def _console(self, alert: Alert):
        color = self.COLORS.get(alert.level, "")
        reset = self.COLORS["RESET"]
        icon = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(alert.level, "📢")
        
        print(f"{color}{icon} [{alert.level}] {alert.title}{reset}")
        print(f"   {alert.message}")
        if alert.data:
            print(f"   Data: {json.dumps(alert.data, indent=2)[:200]}")
    
    def _discord(self, alert: Alert):
        colors = {"INFO": 3447003, "SUCCESS": 5763719, "WARNING": 16776960, "CRITICAL": 15548997}
        
        try:
            requests.post(self.discord_url, json={
                "embeds": [{
                    "title": f"{alert.level}: {alert.title}",
                    "description": alert.message,
                    "color": colors.get(alert.level, 0),
                    "timestamp": alert.timestamp.isoformat()
                }]
            }, timeout=5)
        except Exception as e:
            print(f"  ⚠ Discord failed: {e}")
    
    def _telegram(self, alert: Alert):
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            requests.post(url, json={
                "chat_id": self.telegram_chat,
                "text": f"*{alert.level}*: {alert.title}\n{alert.message}",
                "parse_mode": "Markdown"
            }, timeout=5)
        except Exception as e:
            print(f"  ⚠ Telegram failed: {e}")
    
    def info(self, title: str, message: str, **data):
        self.send(Alert("INFO", title, message, data or None))
    
    def success(self, title: str, message: str, **data):
        self.send(Alert("SUCCESS", title, message, data or None))
    
    def warning(self, title: str, message: str, **data):
        self.send(Alert("WARNING", title, message, data or None))
    
    def critical(self, title: str, message: str, **data):
        self.send(Alert("CRITICAL", title, message, data or None))


# Global instance
notifier = Notifier()


if __name__ == "__main__":
    n = Notifier()
    n.info("Test", "This is an info message")
    n.success("Scan Complete", "Found 3 arbitrage opportunities")
    n.warning("Rate Limit", "Approaching API rate limit")
    n.critical("Big Move!", "BTC market moved 5% in 1 minute", market="bitcoin-2026")

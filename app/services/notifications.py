"""Notification Service - Telegram and Email alerts."""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dataclasses import dataclass

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    """Notification configuration."""
    # Telegram
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # Email (SMTP)
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: list[str] = None
    
    # Thresholds
    alert_on_score_below: int = 80  # Alert if score drops below this
    alert_on_new_failures: bool = True


class NotificationService:
    """Service for sending notifications via various channels."""
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
    
    def send_scan_alert(
        self, 
        scan_id: str, 
        score: float, 
        passed: int, 
        failed: int, 
        devices: int
    ):
        """Send alert about completed scan."""
        if score >= self.config.alert_on_score_below and not self.config.alert_on_new_failures:
            return
        
        subject = f"🔒 HCS Scan Complete: {score}% Score"
        
        message = f"""
**HCS Scan Report**

📊 **Score:** {score}%
✅ **Passed:** {passed}
❌ **Failed:** {failed}
🖥️ **Devices:** {devices}

{"⚠️ Score below threshold!" if score < self.config.alert_on_score_below else ""}

View details: /scans/{scan_id}
"""
        
        self._send_all(subject, message)
    
    def send_score_drop_alert(self, previous_score: float, current_score: float):
        """Send alert when score drops significantly."""
        drop = previous_score - current_score
        if drop < 5:  # Only alert on significant drops
            return
        
        subject = f"⚠️ HCS Score Drop: {previous_score}% → {current_score}%"
        message = f"""
**Security Score Alert**

📉 Score dropped by **{drop:.1f}%**

Previous: {previous_score}%
Current: {current_score}%

Please investigate the new failures.
"""
        self._send_all(subject, message)
    
    def send_custom_alert(self, subject: str, message: str):
        """Send custom alert message."""
        self._send_all(subject, message)
    
    def _send_all(self, subject: str, message: str):
        """Send to all configured channels."""
        if self.config.telegram_enabled:
            self._send_telegram(message)
        
        if self.config.email_enabled:
            self._send_email(subject, message)
    
    def _send_telegram(self, message: str):
        """Send message via Telegram bot."""
        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            logger.warning("Telegram not configured")
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            response = requests.post(url, json={
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"Telegram error: {response.text}")
            else:
                logger.info("Telegram notification sent")
                
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
    
    def _send_email(self, subject: str, body: str):
        """Send email via SMTP."""
        if not all([
            self.config.smtp_host, 
            self.config.smtp_user, 
            self.config.smtp_password,
            self.config.smtp_to
        ]):
            logger.warning("Email not configured")
            return
        
        try:
            msg = MIMEMultipart()
            msg["From"] = self.config.smtp_from or self.config.smtp_user
            msg["To"] = ", ".join(self.config.smtp_to)
            msg["Subject"] = subject
            
            # Convert markdown-ish to plain text
            plain_body = body.replace("**", "").replace("__", "")
            msg.attach(MIMEText(plain_body, "plain"))
            
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                server.starttls()
                server.login(self.config.smtp_user, self.config.smtp_password)
                server.send_message(msg)
            
            logger.info("Email notification sent")
            
        except Exception as e:
            logger.error(f"Email send failed: {e}")
    
    def test_telegram(self) -> tuple[bool, str]:
        """Test Telegram connection."""
        if not self.config.telegram_enabled:
            return False, "Telegram disabled"
        
        try:
            self._send_telegram("🔔 HCS Test notification")
            return True, "Message sent"
        except Exception as e:
            return False, str(e)
    
    def test_email(self) -> tuple[bool, str]:
        """Test email connection."""
        if not self.config.email_enabled:
            return False, "Email disabled"
        
        try:
            self._send_email("HCS Test", "This is a test notification from HCS.")
            return True, "Email sent"
        except Exception as e:
            return False, str(e)


# Singleton instance (configured from environment)
def get_notification_service() -> NotificationService:
    """Get configured notification service."""
    import os
    
    config = NotificationConfig(
        telegram_enabled=bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        
        email_enabled=bool(os.environ.get("SMTP_HOST")),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        smtp_from=os.environ.get("SMTP_FROM", ""),
        smtp_to=(os.environ.get("SMTP_TO", "")).split(",") if os.environ.get("SMTP_TO") else [],
        
        alert_on_score_below=int(os.environ.get("ALERT_SCORE_THRESHOLD", "80")),
    )
    
    return NotificationService(config)

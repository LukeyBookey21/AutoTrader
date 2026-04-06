"""Notification system - email and desktop notifications for alerts."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Email config from environment
SMTP_HOST = os.environ.get("AUTOTRADER_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("AUTOTRADER_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("AUTOTRADER_SMTP_USER", "")
SMTP_PASS = os.environ.get("AUTOTRADER_SMTP_PASS", "")
EMAIL_TO = os.environ.get("AUTOTRADER_EMAIL_TO", "")


def is_email_configured() -> bool:
    """Check if email notifications are configured."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO)


def send_email_notification(subject: str, alerts: list[dict]):
    """Send an email notification with alert details.

    Args:
        subject: Email subject line.
        alerts: List of alert dicts with 'type' and 'message' keys.
    """
    if not is_email_configured():
        logger.debug("Email not configured, skipping notification")
        return False

    # Build HTML body
    rows = ""
    for alert in alerts:
        icon = "&#9660;" if alert.get("type") == "price_drop" else "&#9733;"
        color = "#2e7d32" if alert.get("type") == "price_drop" else "#1a73e8"
        rows += f"""
        <tr>
            <td style="padding:8px;color:{color};font-size:18px;width:30px">{icon}</td>
            <td style="padding:8px;font-size:14px">{alert.get('message', '')}</td>
        </tr>"""

    html = f"""
    <html>
    <body style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">
        <div style="background:#1a73e8;color:white;padding:16px 24px;border-radius:8px 8px 0 0">
            <h2 style="margin:0;font-size:18px">AutoTrader Deal Finder</h2>
        </div>
        <div style="border:1px solid #e0e0e0;border-top:none;border-radius:0 0 8px 8px;padding:16px">
            <p style="color:#666;font-size:14px">{len(alerts)} new alert(s) from your watches:</p>
            <table style="width:100%;border-collapse:collapse">
                {rows}
            </table>
            <hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0">
            <p style="color:#999;font-size:12px">
                View all alerts at your AutoTrader Deal Finder web UI.
            </p>
        </div>
    </body>
    </html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    # Plain text fallback
    plain = "\n".join(
        f"{'[DROP]' if a.get('type') == 'price_drop' else '[NEW]'} {a.get('message', '')}"
        for a in alerts
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info(f"Email notification sent to {EMAIL_TO}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_desktop_notification(title: str, message: str):
    """Send a desktop notification (Linux/Mac).

    Uses notify-send on Linux, osascript on Mac.
    Falls back silently if not available.
    """
    import platform
    import subprocess

    system = platform.system()

    try:
        if system == "Linux":
            subprocess.run(
                ["notify-send", title, message, "--app-name=AutoTrader Deal Finder"],
                capture_output=True, timeout=5,
            )
        elif system == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                capture_output=True, timeout=5,
            )
        else:
            logger.debug(f"Desktop notifications not supported on {system}")
            return False
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.debug("Desktop notification command not available")
        return False


def notify_alerts(alerts: list[dict]):
    """Send notifications for a batch of alerts using all configured channels."""
    if not alerts:
        return

    # Desktop notification (summary)
    count = len(alerts)
    drops = sum(1 for a in alerts if a.get("type") == "price_drop")
    new = count - drops
    parts = []
    if new:
        parts.append(f"{new} new listing(s)")
    if drops:
        parts.append(f"{drops} price drop(s)")
    summary = ", ".join(parts)
    send_desktop_notification("AutoTrader Deal Finder", summary)

    # Email notification
    if is_email_configured():
        send_email_notification(f"AutoTrader Alerts: {summary}", alerts)

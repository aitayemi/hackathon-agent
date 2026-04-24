"""
Email notifier — sends analysis results via SMTP to a configured recipient.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

from agent.config import (
    SMTP_HOST, SMTP_PORT, EMAIL_FROM, EMAIL_TO, EMAIL_ENABLED,
    SMTP_USERNAME, SMTP_PASSWORD,
)

log = logging.getLogger(__name__)


def send_analysis_email(result: dict) -> bool:
    """Send an analysis result as a formatted HTML email. Returns True on success."""
    if not EMAIL_ENABLED:
        return False

    try:
        subject = _build_subject(result)
        html_body = _build_html(result)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg.attach(MIMEText(_build_plain_text(result), "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

        log.info("Analysis email sent to %s", EMAIL_TO)
        return True

    except Exception as e:
        log.warning("Failed to send analysis email: %s: %s", type(e).__name__, e)
        return False


def _build_subject(result: dict) -> str:
    uc1 = result.get("uc1", {}).get("status", "UNKNOWN")
    uc2 = result.get("uc2", {}).get("status", "UNKNOWN")
    cycle = result.get("cycle", "?")

    alerts = []
    if uc1 == "ANOMALY_DETECTED":
        alerts.append("UC1:Supply Chain")
    if uc2 == "ANOMALY_DETECTED":
        alerts.append("UC2:App Store")

    if alerts:
        return f"🔴 ANOMALY DETECTED — {', '.join(alerts)} — Cycle #{cycle}"
    return f"🟢 All Normal — Analysis Cycle #{cycle}"


def _build_plain_text(result: dict) -> str:
    lines = [f"Anomaly Detection Report — Cycle #{result.get('cycle', '?')}"]
    lines.append(f"Timestamp: {result.get('timestamp', 'N/A')}")
    lines.append(f"Total events: {result.get('total_events', 'N/A')}")
    lines.append(f"High-priority events: {result.get('high_priority_count', 'N/A')}")
    lines.append("")

    for uc_key, label in [("uc1", "UC1 — Supply Chain"), ("uc2", "UC2 — App Store Compliance")]:
        uc = result.get(uc_key, {})
        status = uc.get("status", "UNKNOWN")
        confidence = uc.get("confidence", 0)
        action = uc.get("action", "N/A")
        evidence = uc.get("evidence", [])

        lines.append(f"{label}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Confidence: {confidence * 100:.0f}%")
        lines.append(f"  Action: {action}")
        if evidence:
            lines.append("  Evidence:")
            for e in evidence:
                lines.append(f"    - {e}")
        lines.append("")

    reasoning = result.get("reasoning")
    if reasoning:
        lines.append("=" * 60)
        lines.append("EXTENDED THINKING — Model Reasoning")
        lines.append("=" * 60)
        lines.append(reasoning)
        lines.append("")

    return "\n".join(lines)


def _build_html(result: dict) -> str:
    cycle = result.get("cycle", "?")
    ts = result.get("timestamp", "N/A")
    total = result.get("total_events", "N/A")
    hp = result.get("high_priority_count", "N/A")

    sections = []
    for uc_key, label in [("uc1", "UC1 — Supply Chain"), ("uc2", "UC2 — App Store Compliance")]:
        uc = result.get(uc_key, {})
        status = uc.get("status", "UNKNOWN")
        confidence = uc.get("confidence", 0)
        action = uc.get("action", "N/A")
        evidence = uc.get("evidence", [])

        is_anomaly = status == "ANOMALY_DETECTED"
        color = "#dc3545" if is_anomaly else "#28a745"
        bg = "#fff5f5" if is_anomaly else "#f0fff4"
        icon = "🔴" if is_anomaly else "🟢"
        badge = "ANOMALY DETECTED" if is_anomaly else "NORMAL"

        evidence_html = ""
        if evidence:
            items = "".join(f"<li style='margin:4px 0;color:#555'>{e}</li>" for e in evidence)
            evidence_html = f"<ul style='margin:8px 0;padding-left:20px'>{items}</ul>"

        sections.append(f"""
        <div style="background:{bg};border-left:4px solid {color};padding:16px;margin:12px 0;border-radius:4px">
            <h3 style="margin:0 0 8px 0;color:#333">{icon} {label}</h3>
            <span style="background:{color};color:white;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:bold">{badge}</span>
            <span style="margin-left:12px;color:#666">Confidence: <strong>{confidence * 100:.0f}%</strong></span>
            {evidence_html}
            <p style="margin:8px 0 0 0;padding:8px 12px;background:white;border-radius:4px;color:#333;font-size:13px">
                <strong>Recommended Action:</strong> {action}
            </p>
        </div>""")

    return f"""
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#333">
        <div style="background:#1a1d27;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
            <h2 style="margin:0;font-size:18px">🛡️ Anomaly Detection Report</h2>
            <p style="margin:6px 0 0 0;font-size:13px;color:#aaa">Cycle #{cycle} • {ts}</p>
        </div>
        <div style="border:1px solid #e0e0e0;border-top:none;padding:16px;border-radius:0 0 8px 8px">
            <table style="width:100%;font-size:13px;color:#666;margin-bottom:12px">
                <tr>
                    <td>Total events analyzed: <strong>{total}</strong></td>
                    <td>High-priority events: <strong>{hp}</strong></td>
                </tr>
            </table>
            {''.join(sections)}
            <p style="margin:16px 0 0 0;font-size:11px;color:#999;text-align:center">
                Sent by Hackathon Anomaly Detection Agent
            </p>
        </div>
        {_build_reasoning_html(result)}
    </body>
    </html>"""


def _build_reasoning_html(result: dict) -> str:
    """Build the extended thinking section for the HTML email."""
    reasoning = result.get("reasoning")
    if not reasoning:
        return ""

    # Escape HTML and convert newlines to <br>
    import html
    escaped = html.escape(reasoning).replace("\n", "<br>")

    return f"""
        <div style="margin-top:16px;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden">
            <div style="background:#2d3748;color:white;padding:12px 16px">
                <h3 style="margin:0;font-size:14px">🧠 Extended Thinking — Model Reasoning</h3>
            </div>
            <div style="padding:16px;background:#f7fafc;font-size:12px;color:#4a5568;line-height:1.6;font-family:'SF Mono','Fira Code',Consolas,monospace;max-height:600px;overflow-y:auto">
                {escaped}
            </div>
        </div>"""

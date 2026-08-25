"""
dispatch.py
===========
Autonomous alert dispatch â€” HeatShield's unfair advantage.

When the deterministic Response-Gap score crosses CRITICAL (R >= 7.0),
the LangGraph `dispatch_critical_alerts` node fires real-world workflows:
SMS + voice-call alerts to site supervisors via the Twilio REST API.

Graceful degradation is a hard requirement: without Twilio credentials the
node emits DRY-RUN dispatch records with full message previews so judges
see exactly what WOULD have been sent (and can plug keys in live on stage).
The LLM never decides to dispatch â€” only this deterministic gate does.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.utils.clock import utc_now_iso

logger = logging.getLogger("heatshield.dispatch")

TWILIO_SMS_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
)
TWILIO_VOICE_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
)

DEFAULT_CONTACTS = "+15550100201,+15550100202"

DISPATCH_TIMEOUT_S = 8.0


def supervisor_contacts() -> List[str]:
    """Configured supervisor phone numbers (E.164), de-duplicated in order.

    A blank-but-present env var (e.g. `HEATSHIELD_SUPERVISOR_CONTACTS=`
    in .env) must behave exactly like an unset var and fall back to the
    demo contact list.
    """
    raw = os.getenv("HEATSHIELD_SUPERVISOR_CONTACTS") or DEFAULT_CONTACTS
    seen: List[str] = []
    for token in raw.split(","):
        contact = token.strip()
        if contact and contact not in seen:
            seen.append(contact)
    return seen


def twilio_credentials() -> Optional[Dict[str, str]]:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    sender = os.getenv("TWILIO_FROM_NUMBER", "")
    if sid and token and sender:
        return {"sid": sid, "token": token, "from": sender}
    return None


# ---------------------------------------------------------------------------
# Message composition â€” deterministic templates fed by scoring output
# ---------------------------------------------------------------------------

def compose_sms_text(
    site_name: str,
    breakdown: Dict[str, Any],
) -> str:
    r = breakdown.get("response_gap", 0.0)
    tier = breakdown.get("risk_tier", "?")
    peak = breakdown.get("raw_inputs", {}).get("peak_temp_f", "?")
    hours = breakdown.get("raw_inputs", {}).get(
        "consecutive_hours_above_40c", "?"
    )
    return (
        f"HEATSHIELD CRITICAL [{site_name}]: ResponseGap {r}/10 "
        f"({tier}). Peak {peak}F, {hours}h >40C. Halt non-essential "
        f"outdoor work. Move crews to cooling now. Reply 1 = acknowledged."
    )


def compose_voice_script(
    site_name: str,
    breakdown: Dict[str, Any],
) -> str:
    r = breakdown.get("response_gap", 0.0)
    return (
        f"This is HeatShield A I with a critical heat alert for "
        f"{site_name}. The deterministic response gap score is "
        f"{r:.1f} out of 10. Sustained temperatures above 40 degrees "
        f"Celsius detected. Immediately halt non-essential outdoor work "
        f"and move all crews to shaded cooling. This message repeats."
    )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

async def _send_sms(
    creds: Dict[str, str],
    to_number: str,
    text: str,
) -> Dict[str, Any]:
    url = TWILIO_SMS_URL.format(sid=creds["sid"])

    async with httpx.AsyncClient(timeout=DISPATCH_TIMEOUT_S) as client:
        resp = await client.post(
            url,
            data={"To": to_number, "From": creds["from"], "Body": text},
            auth=(creds["sid"], creds["token"]),
        )

    body: Dict[str, Any] = {}
    try:
        body = resp.json()
    except ValueError:
        pass

    if resp.status_code < 300:
        return {
            "status": "sent",
            "provider_ref": body.get("sid"),
            "error": None,
        }

    return {
        "status": "failed",
        "provider_ref": None,
        "error": (
            body.get("message") or f"twilio_http_{resp.status_code}"
        ),
    }


async def _send_voice(
    creds: Dict[str, str],
    to_number: str,
    script: str,
) -> Dict[str, Any]:
    url = TWILIO_VOICE_URL.format(sid=creds["sid"])

    twiml = (
        "<Response><Say voice=\"Polly.Joanna\" loop=\"2\">"
        f"{script}"
        "</Say></Response>"
    )

    async with httpx.AsyncClient(timeout=DISPATCH_TIMEOUT_S) as client:
        resp = await client.post(
            url,
            data={
                "To": to_number,
                "From": creds["from"],
                "Twiml": twiml,
            },
            auth=(creds["sid"], creds["token"]),
        )

    body: Dict[str, Any] = {}
    try:
        body = resp.json()
    except ValueError:
        pass

    if resp.status_code < 300:
        return {
            "status": "sent",
            "provider_ref": body.get("sid"),
            "error": None,
        }

    return {
        "status": "failed",
        "provider_ref": None,
        "error": (
            body.get("message") or f"twilio_http_{resp.status_code}"
        ),
    }


# ---------------------------------------------------------------------------
# Public entry point used by the LangGraph dispatch node
# ---------------------------------------------------------------------------

async def dispatch_critical_alerts(
    *,
    site_name: str,
    latitude: float,
    longitude: float,
    breakdown: Dict[str, Any],
    activity_id: str,
) -> List[Dict[str, Any]]:
    """
    Fire SMS + voice alerts to every configured supervisor.

    Returns per-recipient records; NEVER raises. Without Twilio env
    credentials every record is mode="dry_run" with status="preview".
    """

    contacts = supervisor_contacts()
    creds = twilio_credentials()

    sms_text = compose_sms_text(site_name, breakdown)
    voice_script = compose_voice_script(site_name, breakdown)

    records: List[Dict[str, Any]] = []

    for contact in contacts:

        base_record = {
            "activity_id": activity_id,
            "to": contact,
            "site": site_name,
            "coords": [latitude, longitude],
            "ts": utc_now_iso(),
            "response_gap": breakdown.get("response_gap"),
            "risk_tier": breakdown.get("risk_tier"),
        }

        if creds is None:
            records.append(
                {
                    **base_record,
                    "channel": "sms",
                    "mode": "dry_run",
                    "status": "preview",
                    "preview": sms_text,
                    "error": "no_twilio_credentials",
                }
            )
            records.append(
                {
                    **base_record,
                    "channel": "voice",
                    "mode": "dry_run",
                    "status": "preview",
                    "preview": voice_script,
                    "error": "no_twilio_credentials",
                }
            )
            continue

        try:
            sms_result = await _send_sms(creds, contact, sms_text)
        except Exception as exc:
            sms_result = {"status": "failed", "provider_ref": None, "error": repr(exc)}

        records.append(
            {
                **base_record,
                "channel": "sms",
                "mode": "live",
                "status": sms_result["status"],
                "provider_ref": sms_result["provider_ref"],
                "error": sms_result["error"],
            }
        )

        try:
            voice_result = await _send_voice(creds, contact, voice_script)
        except Exception as exc:
            voice_result = {
                "status": "failed",
                "provider_ref": None,
                "error": repr(exc),
            }

        records.append(
            {
                **base_record,
                "channel": "voice",
                "mode": "live",
                "status": voice_result["status"],
                "provider_ref": voice_result["provider_ref"],
                "error": voice_result["error"],
            }
        )

    logger.info(
        "Dispatch complete: %d records (%d dry-run)",
        len(records),
        sum(1 for r in records if r["mode"] == "dry_run"),
    )

    return records

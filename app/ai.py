from __future__ import annotations

import json
import re
from typing import Any
from urllib import error, request

from .config import (
    CONFIDENCE_LABELS,
    EXPENSIVE_PART_KEYWORDS,
    OLLAMA_ENABLED,
    OLLAMA_MODEL,
    OLLAMA_URL,
    REPAIR_CATEGORIES,
)


SPANISH_HINTS = {
    "unidad",
    "camion",
    "troca",
    "falla",
    "arreglado",
    "listo",
    "cambie",
    "cambio",
    "freno",
    "frenos",
    "bateria",
    "arranca",
    "calienta",
    "manguera",
    "pago",
    "pagado",
    "factura",
}

FIELD_NAMES = [
    "original_language",
    "english_translation",
    "unit_number",
    "technician_name",
    "customer_name",
    "location",
    "complaint",
    "diagnosis",
    "repair_performed",
    "part_used",
    "part_number",
    "quantity",
    "job_status",
    "payment_amount",
    "payment_status",
    "missing_information",
    "confidence_label",
    "confidence_reason",
    "repair_category",
    "translation_uncertain",
]


def blank_extraction() -> dict[str, Any]:
    return {
        "original_language": "Unknown",
        "english_translation": "",
        "unit_number": "",
        "technician_name": "",
        "customer_name": "",
        "location": "",
        "complaint": "",
        "diagnosis": "",
        "repair_performed": "",
        "part_used": "",
        "part_number": "",
        "quantity": None,
        "job_status": "",
        "payment_amount": None,
        "payment_status": "",
        "missing_information": [],
        "confidence_label": "Unconfirmed",
        "confidence_reason": "No reliable job details were found.",
        "repair_category": "Unknown",
        "translation_uncertain": False,
    }


def detect_language(text: str) -> str:
    lowered = text.lower()
    if not lowered.strip():
        return "Unknown"
    if any(ch in lowered for ch in ["\u00f1", "\u00e1", "\u00e9", "\u00ed", "\u00f3", "\u00fa"]):
        return "Spanish"
    if any(word in lowered for word in SPANISH_HINTS):
        return "Spanish"
    if re.search(r"[^\x00-\x7f]", text):
        return "Native/Other"
    return "English"


def translate_fallback(text: str, language: str) -> tuple[str, bool]:
    if language == "English":
        return text, False
    if not text.strip():
        return "", False
    replacements = {
        "unidad": "unit",
        "camion": "truck",
        "troca": "truck",
        "no arranca": "does not start",
        "arranca": "starts",
        "falla": "fault",
        "listo": "ready",
        "arreglado": "fixed",
        "cambie": "changed",
        "cambio": "changed",
        "freno": "brake",
        "frenos": "brakes",
        "bateria": "battery",
        "manguera": "hose",
        "pago": "payment",
        "pagado": "paid",
        "factura": "invoice",
    }
    translated = text
    for source, target in replacements.items():
        translated = re.sub(source, target, translated, flags=re.IGNORECASE)
    uncertain = translated == text or language != "Spanish"
    return translated, uncertain


def _regex_first(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return next((group for group in match.groups() if group), match.group(0)).strip(" .,:;#")
    return ""


def _extract_quantity(text: str) -> float | None:
    match = re.search(r"\b(?:qty|quantity|cant|x)\s*[:#-]?\s*(\d+(?:\.\d+)?)\b", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*x\s+(?:starter|battery|tire|sensor|chamber|hose|filter|bag)\b", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def detect_repair_category(text: str) -> str:
    lowered = text.lower()
    category_keywords = [
        ("Starting/Charging", ["no start", "starter", "alternator", "battery", "charging", "no arranca"]),
        ("Brakes", ["brake", "freno", "frenos", "chamber", "slack adjuster", "drum", "rotor"]),
        ("Air System", ["air leak", "air line", "air bag", "compressor", "governor"]),
        ("Cooling System", ["overheat", "coolant", "radiator", "water pump", "fan clutch"]),
        ("Fuel System", ["fuel", "injector", "pump", "diesel"]),
        ("Electrical", ["wiring", "wire", "electrical", "short", "light", "sensor", "code"]),
        ("Engine", ["engine", "oil leak", "misfire", "turbo", "egr"]),
        ("Transmission", ["transmission", "clutch", "gear", "shift"]),
        ("Suspension", ["suspension", "leaf spring", "shock", "air bag"]),
        ("Steering", ["steering", "tie rod", "kingpin"]),
        ("Tires/Wheels", ["tire", "wheel", "lug", "hub"]),
        ("Exhaust/DPF/DEF", ["dpf", "def", "regen", "exhaust", "aftertreatment"]),
        ("HVAC", ["ac", "a/c", "hvac", "heater", "blower"]),
        ("Diagnostics", ["diagnostic", "diagnosis", "diag", "scan", "code"]),
        ("Trailer/Body", ["trailer", "door", "body", "liftgate", "reefer"]),
    ]
    for category, words in category_keywords:
        if any(word in lowered for word in words):
            return category
    return "Unknown"


def _extract_status(text: str) -> str:
    lowered = text.lower()
    if any(phrase in lowered for phrase in ["waiting for parts", "part ordered", "parts ordered", "need part"]):
        return "waiting_parts"
    if any(phrase in lowered for phrase in ["waiting approval", "need approval", "approve repair", "pending approval"]):
        return "waiting_approval"
    if any(phrase in lowered for phrase in ["payment pending", "need payment", "unpaid", "balance due"]):
        return "payment_pending"
    if any(phrase in lowered for phrase in ["done", "fixed", "complete", "completed", "truck ready", "unit ready", "listo", "arreglado"]):
        return "completed_unverified"
    if any(phrase in lowered for phrase in ["working on", "diagnosing", "checking", "in progress", "on it"]):
        return "ongoing"
    return ""


def _extract_payment_status(text: str) -> str:
    lowered = text.lower()
    if any(phrase in lowered for phrase in ["paid", "pagado", "payment received", "zelle sent", "cash received"]):
        return "paid_unverified"
    if any(phrase in lowered for phrase in ["payment pending", "unpaid", "balance due", "need payment", "pending payment"]):
        return "pending"
    if "partial" in lowered:
        return "partial_unverified"
    return ""


def _extract_part(text: str) -> str:
    patterns = [
        r"\b(?:replaced|installed|changed|cambie|cambio)\s+(?:the\s+)?([a-z0-9 /-]{3,40})",
        r"\b(?:part used|parts used|part)\s*[:#-]\s*([a-z0-9 /-]{3,40})",
        r"\b(starter|alternator|battery|brake chamber|air bag|sensor|hose|radiator|turbo|injector|filter|tire|wheel seal|compressor)\b",
    ]
    part = _regex_first(patterns, text)
    if part:
        part = re.split(r"\b(?:on|for|unit|truck|qty|pn|part number|and)\b", part, flags=re.IGNORECASE)[0]
    return part.strip(" .,:;-")


def _missing_information(extraction: dict[str, Any], text: str) -> list[str]:
    missing: list[str] = []
    lowered = text.lower()
    if not extraction["unit_number"]:
        missing.append("unit_number")
    if extraction["job_status"] == "completed_unverified" and not any(
        word in lowered for word in ["tested", "road test", "verified", "confirmed", "test result"]
    ):
        missing.append("test_result")
    if extraction["payment_amount"] is not None and not extraction["unit_number"]:
        missing.append("payment_unit_or_job")
    if extraction["part_used"] and not extraction["unit_number"]:
        missing.append("part_unit_number")
    if extraction["part_used"] and any(word in extraction["part_used"].lower() for word in EXPENSIVE_PART_KEYWORDS):
        if not extraction["part_number"]:
            missing.append("part_number")
    if extraction["translation_uncertain"]:
        missing.append("translation_verification")
    return sorted(set(missing))


def fallback_extract(normalized: dict[str, Any]) -> dict[str, Any]:
    text = normalized.get("text", "") or ""
    extraction = blank_extraction()
    language = detect_language(text)
    translation, translation_uncertain = translate_fallback(text, language)
    extraction["original_language"] = language
    extraction["english_translation"] = translation
    extraction["translation_uncertain"] = translation_uncertain
    extraction["technician_name"] = normalized.get("sender_name", "") or ""
    extraction["unit_number"] = _regex_first(
        [
            r"\b(?:unit|truck|tractor|trk|unidad|camion|troca)\s*#?\s*([a-z]?\d{2,6}[a-z]?)\b",
            r"\b#\s*([a-z]?\d{2,6}[a-z]?)\b",
        ],
        text,
    )
    extraction["customer_name"] = _regex_first(
        [
            r"\b(?:customer|client|company|for)\s*[:#-]?\s*([A-Z][A-Za-z0-9 &.-]{2,40})",
            r"\b(?:cliente|compania)\s*[:#-]?\s*([A-Z][A-Za-z0-9 &.-]{2,40})",
        ],
        text,
        flags=0,
    )
    extraction["location"] = _regex_first(
        [
            r"\b(?:at|in|location|yard|shop)\s+([A-Za-z0-9 &.-]{3,50})",
            r"\b(?:ubicacion|en)\s+([A-Za-z0-9 &.-]{3,50})",
        ],
        text,
    )
    extraction["complaint"] = _regex_first(
        [
            r"\b(?:complaint|issue|problem|falla)\s*[:#-]\s*([^.;\n]{3,120})",
            r"\b(no start|does not start|no arranca|overheating|air leak|brake noise|check engine|won't start|will not start)\b",
        ],
        text,
    )
    extraction["diagnosis"] = _regex_first(
        [
            r"\b(?:found|diagnosis|diag|diagnosed|cause)\s*[:#-]?\s*([^.;\n]{3,140})",
            r"\b(?:bad|failed|leaking|broken)\s+([^.;\n]{3,80})",
        ],
        text,
    )
    extraction["repair_performed"] = _regex_first(
        [
            r"\b(?:repaired|replaced|installed|changed|fixed|cleaned|adjusted|cambie|cambio)\s+([^.;\n]{3,140})",
            r"\b(?:repair performed|work done)\s*[:#-]\s*([^.;\n]{3,140})",
        ],
        text,
    )
    extraction["part_used"] = _extract_part(text)
    extraction["part_number"] = _regex_first(
        [
            r"\b(?:part number|part no|pn|p/n)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9.-]{2,30})\b",
        ],
        text,
    )
    extraction["quantity"] = _extract_quantity(text)
    extraction["job_status"] = _extract_status(text)
    amount = _regex_first([r"\$\s*([0-9][0-9,]*(?:\.\d{2})?)", r"\b(?:amount|total|invoice)\s*[:#-]?\s*([0-9][0-9,]*(?:\.\d{2})?)"], text)
    extraction["payment_amount"] = float(amount.replace(",", "")) if amount else None
    extraction["payment_status"] = _extract_payment_status(text)
    extraction["repair_category"] = detect_repair_category(text)
    extraction["missing_information"] = _missing_information(extraction, text)

    evidence_count = sum(
        bool(extraction[key])
        for key in ["unit_number", "complaint", "diagnosis", "repair_performed", "part_used", "job_status", "payment_status"]
    )
    if evidence_count >= 3 and extraction["unit_number"]:
        extraction["confidence_label"] = "Confirmed"
        extraction["confidence_reason"] = "Message contains a unit number plus multiple concrete job details."
    elif evidence_count >= 1:
        extraction["confidence_label"] = "Likely"
        extraction["confidence_reason"] = "Message contains some job evidence but needs human verification."
    else:
        extraction["confidence_label"] = "Unconfirmed"
        extraction["confidence_reason"] = "Message is too vague for a reliable job summary."
    if extraction["translation_uncertain"]:
        extraction["confidence_label"] = "Unconfirmed"
        extraction["confidence_reason"] = "Translation requires human verification."
    return extraction


def _clean_ai_response(data: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    cleaned = blank_extraction()
    cleaned.update(fallback)
    for key in FIELD_NAMES:
        if key in data and data[key] not in (None, "", []):
            cleaned[key] = data[key]
    if cleaned["confidence_label"] not in CONFIDENCE_LABELS:
        cleaned["confidence_label"] = fallback["confidence_label"]
    if cleaned["repair_category"] not in REPAIR_CATEGORIES:
        cleaned["repair_category"] = fallback["repair_category"]
    if not isinstance(cleaned.get("missing_information"), list):
        cleaned["missing_information"] = fallback["missing_information"]
    return cleaned


def ollama_extract(normalized: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any] | None:
    if not OLLAMA_ENABLED:
        return None
    text = normalized.get("text", "") or ""
    if not text.strip():
        return None
    prompt = f"""
You extract fleet repair facts from one WhatsApp message for a read-only dashboard.
Never invent part numbers, prices, labor hours, customer names, invoice numbers, or missing facts.
Use null or an empty string when the message does not state a fact.
Confidence label must be one of: Confirmed, Likely, Unconfirmed, Conflicting.
Return only JSON with these keys: {", ".join(FIELD_NAMES)}.

Message metadata:
sender_name={normalized.get("sender_name", "")}
group_name={normalized.get("group_name", "")}

Message:
{text}
"""
    body = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")
    req = request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload.get("response", "{}")
        return _clean_ai_response(json.loads(content), fallback)
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


def extract_message(normalized: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_extract(normalized)
    ai_result = ollama_extract(normalized, fallback)
    return ai_result or fallback


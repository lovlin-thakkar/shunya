"""Voice Quirks DSL — shared parsing utilities used by caller and load_scenarios."""
import re

QUIRK_PATTERN = re.compile(r"\[(\w+)(?::(?:\"([^\"]*)\"|([^\]]+)))?\]")

VALUE_QUIRKS = {"phone", "email", "hard_input"}


def strip_quirks(text: str) -> str:
    def _replace(m):
        tag = m.group(1)
        value = m.group(2) or m.group(3) or ""
        return value if tag in VALUE_QUIRKS and value else ""
    return QUIRK_PATTERN.sub(_replace, text).strip()


def extract_quirk_tags(text: str) -> list[str]:
    return [m.group(1) for m in QUIRK_PATTERN.finditer(text)]


def parse_step(raw: str) -> dict:
    quirks = []
    for m in QUIRK_PATTERN.finditer(raw):
        tag, value = m.group(1), m.group(2)
        quirks.append({"tag": tag, "value": value} if value else {"tag": tag})
    return {"text": strip_quirks(raw), "raw": raw, "quirks": quirks}

from __future__ import annotations


MOJIBAKE_MARKERS = ("å", "æ", "ç", "è", "é", "ä", "Â", "Ã", "\ufffd")


def repair_mojibake(value: str | None) -> str:
    if not value:
        return ""

    text = str(value)
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text

    try:
        repaired = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text

    if _score_readability(repaired) > _score_readability(text):
        return repaired
    return text


def _score_readability(value: str) -> int:
    chinese = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    controls = sum(1 for char in value if ord(char) < 32 or 127 <= ord(char) <= 159)
    markers = sum(value.count(marker) for marker in MOJIBAKE_MARKERS)
    return chinese * 3 - controls * 4 - markers

from datetime import UTC, datetime

from app.domain.schemas import Penalty


def build_penalties(flags: list[dict], rules: dict) -> list[Penalty]:
    result: list[Penalty] = []
    configured = rules["penalties"]
    for flag in flags:
        code = flag["code"]
        if code not in configured:
            raise ValueError(f"Unknown penalty code: {code}")
        minimum, maximum = configured[code]
        points = int(flag.get("points", maximum))
        if not minimum <= points <= maximum:
            raise ValueError(f"Penalty {code} outside configured range")
        result.append(Penalty(code=code, reason=flag["reason"], points=points, source=flag["source"], timestamp=flag.get("timestamp", datetime.now(UTC))))
    return result


def parse_duration(text):
    """Parse a duration like '1h 30m' into minutes."""

    total = 0
    for raw_part in text.split(" "):
        part = raw_part.strip()
        if not part:
            continue
        unit = part[-1]
        value = int(part[:-1])
        if unit == "h":
            total += value * 60
        elif unit == "m":
            total += value
        elif unit == "s":
            total += value
        else:
            raise ValueError(f"unknown duration unit: {unit}")
    return total

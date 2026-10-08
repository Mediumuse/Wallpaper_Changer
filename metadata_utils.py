import html
import re


UNKNOWN_DATE = "Unknown"


def normalize_artwork_date(value):
    if not isinstance(value, str):
        return UNKNOWN_DATE

    clean_date = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
    if not clean_date:
        return UNKNOWN_DATE

    structured_year = re.fullmatch(
        r"(\d{4})date\s+QS:P\d+,\+?\d{4}-\d{2}-\d{2}"
        r"T\d{2}:\d{2}:\d{2}Z(?:/\d+)?",
        clean_date,
        re.IGNORECASE,
    )
    if structured_year:
        return structured_year.group(1)

    iso_date = re.match(
        r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?:[T ]|$)",
        clean_date,
    )
    if iso_date:
        year, month, day = iso_date.groups()
        if month and month != "00" and 1 <= int(month) <= 12:
            if day and day != "00" and 1 <= int(day) <= 31:
                return f"{year}-{month}-{day}"
            return f"{year}-{month}"
        return year

    if re.fullmatch(r"\d{4}", clean_date):
        return clean_date

    circa_year = re.fullmatch(r"(?:circa|c\.?)\s*(\d{4})", clean_date, re.IGNORECASE)
    if circa_year:
        return f"circa {circa_year.group(1)}"

    return UNKNOWN_DATE

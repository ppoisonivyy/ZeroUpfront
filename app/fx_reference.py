"""Read the historical USD/THB reference for the fictional Pattaya trade."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.pattaya_agents import GUARANTEE_MINOR, TRADE_DATE


PROVIDER = {"provider": "Frankfurter", "publisher": "ECB",
            "source_url": "https://frankfurter.dev/providers/ecb"}
ENDPOINT = "https://api.frankfurter.dev/v2/rate/USD/THB"


@lru_cache(maxsize=8)
def _historical_rate(trade_date):
    request = Request(f"{ENDPOINT}?date={trade_date.isoformat()}&providers=ECB",
                      headers={"Accept":"application/json", "User-Agent":"ZeroUpfront/1.0"})
    with urlopen(request, timeout=4) as response:
        body = response.read(2049)
    if len(body) > 2048:
        raise ValueError("Unexpected reference response size")
    item = json.loads(body, parse_float=Decimal)
    if item["base"] != "USD" or item["quote"] != "THB":
        raise ValueError("Unexpected currency pair")
    as_of = date.fromisoformat(item["date"])
    rate = Decimal(str(item["rate"]))
    if not trade_date - timedelta(days=7) <= as_of <= trade_date or not rate.is_finite() or not 1 <= rate <= 1000:
        raise ValueError("Reference outside expected date or currency bounds")
    return as_of, rate


def reference():
    try:
        as_of, rate = _historical_rate(date.fromisoformat(TRADE_DATE))
    except (URLError, OSError, ValueError, TypeError, KeyError, ArithmeticError):
        return {**PROVIDER, "status": "unavailable"}
    return {**PROVIDER, "status": "available", "rate_date": as_of.isoformat(),
            "rate_thb_per_usd": str(rate),
            "usd_minor": int((Decimal(GUARANTEE_MINOR) / rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))}

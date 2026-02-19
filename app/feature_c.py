import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ALLOWED_HOURLY = {
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "surface_pressure",
}


def _http_get_json(url: str, params: Dict[str, object], timeout_sec: int = 20) -> Dict[str, object]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        detail = f"HTTP Error {e.code}"
        if body:
            detail = f"{detail}: {body[:300]}"
        raise RuntimeError(detail) from e


def _resolve_location(location: str) -> Dict[str, object]:
    payload = _http_get_json(
        GEOCODE_URL,
        {"name": location, "count": 1, "language": "en", "format": "json"},
        timeout_sec=20,
    )
    results = payload.get("results") or []
    if not results:
        raise ValueError(f"Location not found: {location}")
    first = results[0]
    return {
        "name": first.get("name", location),
        "country": first.get("country", ""),
        "latitude": first.get("latitude"),
        "longitude": first.get("longitude"),
        "timezone": first.get("timezone", "auto"),
    }


def _validate_dates(start_date: str, end_date: str) -> None:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end < start:
        raise ValueError("end_date must be >= start_date")
    if (end - start).days > 31:
        raise ValueError("Date range too large; use at most 31 days")
    today = date.today()
    if start < date(1940, 1, 1) or end > today.replace(year=today.year + 1):
        raise ValueError("Date range out of supported bounds")


def _fetch_weather_series(location: str, start_date: str, end_date: str, hourly_var: str) -> Dict[str, object]:
    if hourly_var not in ALLOWED_HOURLY:
        raise ValueError(f"Unsupported hourly variable: {hourly_var}")
    _validate_dates(start_date, end_date)
    geo = _resolve_location(location)
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    today = date.today()
    # Open-Meteo historical data requires archive endpoint.
    if end <= today:
        weather_url = ARCHIVE_URL
    elif start >= today:
        weather_url = FORECAST_URL
    else:
        raise ValueError("Date range that crosses past and future is not supported in one request")

    payload = _http_get_json(
        weather_url,
        {
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "hourly": hourly_var,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "auto",
        },
        timeout_sec=25,
    )
    hourly = payload.get("hourly", {})
    times = hourly.get("time") or []
    values = hourly.get(hourly_var) or []
    if not times or not values or len(times) != len(values):
        raise RuntimeError("Open-Meteo returned incomplete hourly data")
    if len(times) > 24 * 35:
        raise RuntimeError("Returned series too large for sandbox processing")

    return {
        "meta": {
            "location_name": geo["name"],
            "country": geo["country"],
            "latitude": geo["latitude"],
            "longitude": geo["longitude"],
            "timezone": payload.get("timezone", "auto"),
            "hourly_var": hourly_var,
            "hourly_units": (payload.get("hourly_units") or {}).get(hourly_var, ""),
            "start_date": start_date,
            "end_date": end_date,
        },
        "time": times,
        "values": values,
    }


def _sandbox_analysis(weather_payload: Dict[str, object], timeout_sec: int = 8) -> Dict[str, object]:
    sandbox_code = r"""
import json
import math
import statistics
import sys

def rolling_avg(vals, window):
    out = []
    for i in range(len(vals)):
        left = max(0, i - window + 1)
        chunk = [x for x in vals[left:i+1] if x is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out

def summarize(meta, time, values):
    n = len(values)
    clean = [v for v in values if isinstance(v, (int, float))]
    missing = n - len(clean)
    miss_rate = (missing / n) if n else 0.0
    if not clean:
        raise ValueError("No numeric values in series")

    mean_v = statistics.fmean(clean)
    stdev_v = statistics.pstdev(clean) if len(clean) > 1 else 0.0
    min_v = min(clean)
    max_v = max(clean)
    roll = rolling_avg(values, 24)

    anomalies = []
    if stdev_v > 0:
        upper = mean_v + 2.5 * stdev_v
        lower = mean_v - 2.5 * stdev_v
        for i, v in enumerate(values):
            if isinstance(v, (int, float)) and (v > upper or v < lower):
                anomalies.append({"time": time[i], "value": v})
                if len(anomalies) >= 10:
                    break

    daily_volatility = []
    current_day = None
    bucket = []
    for t, v in zip(time, values):
        d = t[:10]
        if current_day is None:
            current_day = d
        if d != current_day:
            nums = [x for x in bucket if isinstance(x, (int, float))]
            vol = statistics.pstdev(nums) if len(nums) > 1 else 0.0
            daily_volatility.append({"day": current_day, "volatility": vol})
            current_day = d
            bucket = []
        bucket.append(v)
    if current_day is not None:
        nums = [x for x in bucket if isinstance(x, (int, float))]
        vol = statistics.pstdev(nums) if len(nums) > 1 else 0.0
        daily_volatility.append({"day": current_day, "volatility": vol})

    top_vol_days = sorted(daily_volatility, key=lambda x: x["volatility"], reverse=True)[:3]
    roll_tail = [x for x in roll[-24:] if isinstance(x, (int, float))]
    trend = "flat"
    if len(roll_tail) >= 2:
        delta = roll_tail[-1] - roll_tail[0]
        if delta > 0.5:
            trend = "rising"
        elif delta < -0.5:
            trend = "falling"

    return {
        "series_points": n,
        "missing_count": missing,
        "missing_rate": round(miss_rate, 4),
        "mean": round(mean_v, 4),
        "std_dev": round(stdev_v, 4),
        "min": round(min_v, 4),
        "max": round(max_v, 4),
        "trend_24h_rolling": trend,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "top_volatile_days": top_vol_days,
    }

payload = json.loads(sys.stdin.read())
meta = payload["meta"]
time = payload["time"]
values = payload["values"]
summary = summarize(meta, time, values)
print(json.dumps({"meta": meta, "summary": summary}))
"""
    with tempfile.TemporaryDirectory(prefix="feature_c_") as td:
        script_path = Path(td) / "sandbox_job.py"
        script_path.write_text(sandbox_code, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-I", str(script_path)],
            input=json.dumps(weather_payload),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            cwd=td,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or "sandbox execution failed"
            raise RuntimeError(err)
        return json.loads(proc.stdout)


def _explain_findings(result: Dict[str, object]) -> str:
    meta = result["meta"]
    s = result["summary"]
    units = meta.get("hourly_units", "")
    unit_txt = f" {units}" if units else ""
    lines = [
        f"Weather analysis for {meta['location_name']}, {meta['country']} ({meta['start_date']} to {meta['end_date']}) on `{meta['hourly_var']}`.",
        f"Collected {s['series_points']} hourly points. Missingness: {s['missing_count']} ({round(float(s['missing_rate']) * 100, 2)}%).",
        f"Range: {s['min']}{unit_txt} to {s['max']}{unit_txt}; mean {s['mean']}{unit_txt}; volatility (std dev) {s['std_dev']}{unit_txt}.",
        f"24h rolling average trend appears `{s['trend_24h_rolling']}`.",
        f"Anomaly flags: {s['anomaly_count']} points beyond +/-2.5 std dev.",
    ]
    top_days = s.get("top_volatile_days") or []
    if top_days:
        days = ", ".join(f"{d['day']} (vol={round(d['volatility'], 3)})" for d in top_days)
        lines.append(f"Most volatile days: {days}.")
    return "\n".join(lines)


def run_weather_analysis(
    location: str,
    start_date: str,
    end_date: str,
    hourly_var: str = "temperature_2m",
) -> Dict[str, object]:
    weather_payload = _fetch_weather_series(location=location, start_date=start_date, end_date=end_date, hourly_var=hourly_var)
    sandbox_result = _sandbox_analysis(weather_payload)
    explanation = _explain_findings(sandbox_result)
    return {
        "feature": "C",
        "tool": "open-meteo",
        "sandbox": {"engine": "python_subprocess_isolated", "timeout_sec": 8, "mode": "no-site (-I)"},
        "meta": sandbox_result["meta"],
        "summary": sandbox_result["summary"],
        "explanation": explanation,
    }

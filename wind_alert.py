#!/usr/bin/env python3
"""
Wind Alerter - monitora vento e temporali, manda notifica Telegram.

- Usa Open-Meteo (gratis, no API key)
- Solo libreria standard di Python 3 (niente pip install)
- Deduplica gli alert via state.json
- Rileva cambi repentini e fa preavviso 1-3h

Config e state sono nella stessa cartella dello script.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Forza timezone Europe/Rome anche su runner UTC (es. GitHub Actions)
os.environ["TZ"] = "Europe/Rome"
if hasattr(time, "tzset"):
    time.tzset()

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.json"
STATE_PATH = SCRIPT_DIR / "state.json"
LOG_PATH = SCRIPT_DIR / "wind_alert.log"

LEVEL_ORDER = {"ok": 0, "warning": 1, "critical": 2}
EMOJI = {"ok": "OK", "warning": "WARNING", "critical": "CRITICO"}

WEATHER_CODE = {
    0: "sereno", 1: "prev. sereno", 2: "poco nuvoloso", 3: "coperto",
    45: "nebbia", 48: "nebbia gelata",
    51: "pioviggine lieve", 53: "pioviggine", 55: "pioviggine intensa",
    61: "pioggia lieve", 63: "pioggia", 65: "pioggia forte",
    66: "pioggia gelata", 67: "pioggia gelata forte",
    71: "neve lieve", 73: "neve", 75: "neve intensa", 77: "granelli di neve",
    80: "rovesci lievi", 81: "rovesci", 82: "rovesci violenti",
    85: "rovesci di neve", 86: "rovesci di neve forti",
    95: "TEMPORALE", 96: "TEMPORALE con grandine", 99: "TEMPORALE forte con grandine",
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line, end="")
    try:
        # Trim log se supera 500 KB
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 500_000:
            LOG_PATH.write_text(LOG_PATH.read_text().splitlines(keepends=True)[-2000:][0:])  # noqa
        with open(LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"ERRORE: config.json non trovato in {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def fetch_weather(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
                   "precipitation,weather_code,temperature_2m",
        "hourly": "wind_speed_10m,wind_gusts_10m,precipitation,weather_code",
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Rome",
        "forecast_days": 2,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "wind-alerter/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status == 200


def classify(gust: float, warning: float, critical: float) -> str:
    if gust >= critical:
        return "critical"
    if gust >= warning:
        return "warning"
    return "ok"


def direction_label(deg: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return dirs[int((deg + 11.25) / 22.5) % 16]


def parse_open_meteo_time(t: str) -> datetime:
    # Open-Meteo restituisce timestamp senza tz ma già in tz richiesta
    return datetime.fromisoformat(t)


def is_in_quiet_hours(now: datetime, qh: dict) -> bool:
    if not qh.get("enabled"):
        return False
    start = int(qh.get("start_hour", 23))
    end = int(qh.get("end_hour", 7))
    h = now.hour
    if start <= end:
        return start <= h < end
    return h >= start or h < end


def main() -> int:
    cfg = load_config()

    # Leggi credenziali: preferisci env vars (GitHub Actions), fallback config.json
    tg = cfg.get("telegram", {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or str(tg.get("chat_id", ""))
    if not token or token.startswith("PASTE") or not chat_id or chat_id.startswith("PASTE"):
        log("ERRORE: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID mancanti (env o config)")
        return 1

    loc = cfg["location"]
    lat, lon = float(loc["latitude"]), float(loc["longitude"])
    loc_name = loc.get("name", "Posizione")

    thr = cfg.get("thresholds", {})
    warning_thr = float(thr.get("warning_gust_kmh", 30))
    critical_thr = float(thr.get("critical_gust_kmh", 50))
    delta_thr = float(thr.get("sudden_delta_kmh", 15))
    forecast_h = int(thr.get("forecast_hours", 3))

    qh = cfg.get("quiet_hours", {"enabled": False})

    try:
        data = fetch_weather(lat, lon)
    except Exception as e:
        log(f"ERRORE fetch Open-Meteo: {e}")
        return 1

    cur = data["current"]
    gust = float(cur["wind_gusts_10m"])
    speed = float(cur["wind_speed_10m"])
    wdir = float(cur["wind_direction_10m"])
    precip = float(cur.get("precipitation", 0) or 0)
    wcode = int(cur["weather_code"])
    temp = cur.get("temperature_2m")

    hourly = data["hourly"]
    now = datetime.now()

    # Previsione prossime N ore
    future = []
    for t, g, c in zip(hourly["time"], hourly["wind_gusts_10m"], hourly["weather_code"]):
        try:
            tdt = parse_open_meteo_time(t)
        except Exception:
            continue
        if tdt <= now:
            continue
        if len(future) >= forecast_h:
            break
        future.append((tdt, float(g), int(c)))

    max_fg = max((g for _, g, _ in future), default=0.0)
    max_fg_t = next((t for t, g, _ in future if g == max_fg), None)
    future_storms = [(t, c) for t, _, c in future if c in (95, 96, 99)]

    cur_level = classify(gust, warning_thr, critical_thr)
    fcst_level = classify(max_fg, warning_thr, critical_thr)

    state = load_state()
    prev_level = state.get("last_level", "ok")
    history = state.get("history", [])
    history.append({"ts": now.strftime("%Y-%m-%d %H:%M"), "gust": gust, "speed": speed})
    history = history[-12:]  # ultime ~3 ore

    # Rilevamento cambio repentino: confronto con lettura ~30 min fa
    sudden_delta = 0.0
    if len(history) >= 3:
        ref = float(history[-3]["gust"])  # 2 step indietro = ~30 min
        sudden_delta = gust - ref

    alerts = []

    # 1. Salto di livello verso l'alto (ok→warn, ok→crit, warn→crit)
    if LEVEL_ORDER[cur_level] > LEVEL_ORDER[prev_level]:
        alerts.append(("level_up", cur_level))

    # 2. Cambio repentino (solo se valore già rilevante)
    if sudden_delta >= delta_thr and gust >= warning_thr * 0.6:
        alerts.append(("sudden", sudden_delta))

    # 3. Preavviso: ora stiamo OK ma la previsione dice warning/critical
    #    cooldown 2h per non ripetere lo stesso preavviso
    last_fcst_ts = state.get("last_forecast_alert_ts")
    cooldown_h = 2
    can_warn_fcst = True
    if last_fcst_ts:
        try:
            last_dt = datetime.fromisoformat(last_fcst_ts)
            can_warn_fcst = (now - last_dt).total_seconds() / 3600 >= cooldown_h
        except Exception:
            can_warn_fcst = True
    if cur_level == "ok" and LEVEL_ORDER[fcst_level] >= 1 and can_warn_fcst:
        alerts.append(("forecast", (max_fg, max_fg_t, fcst_level)))

    # 4. Temporale ora
    if wcode in (95, 96, 99) and state.get("last_storm_code") != wcode:
        alerts.append(("storm_now", wcode))

    # 5. Temporale previsto (una volta sola finché rimane previsto)
    if future_storms and not state.get("storm_forecast_warned"):
        alerts.append(("storm_forecast", future_storms[0]))

    # 6. Rientro dopo periodo elevato
    if prev_level != "ok" and cur_level == "ok":
        alerts.append(("recovery", prev_level))

    if alerts:
        in_quiet = is_in_quiet_hours(now, qh)
        has_critical = any(
            (k == "level_up" and v == "critical") or k == "storm_now"
            for k, v in alerts
        )
        if in_quiet and not has_critical:
            log(f"Alert soppressi per quiet hours: {[a[0] for a in alerts]}")
        else:
            lines = [f"<b>🌬️ Monitor vento - {loc_name}</b>"]
            for kind, payload in alerts:
                if kind == "level_up":
                    level = payload
                    soglia = "CRITICA" if level == "critical" else "WARNING"
                    lines.append(f"\n🚨 <b>SOGLIA {soglia} SUPERATA</b>")
                    lines.append(f"Raffica attuale: <b>{gust:.0f} km/h</b>")
                elif kind == "sudden":
                    lines.append(f"\n⚡ <b>CAMBIO REPENTINO</b>")
                    lines.append(f"Raffica aumentata di +{payload:.0f} km/h in ~30 min")
                    lines.append(f"Ora: <b>{gust:.0f} km/h</b>")
                elif kind == "forecast":
                    g_f, t_f, lev_f = payload
                    t_fmt = t_f.strftime("%H:%M") if t_f else "prossime ore"
                    tag = "CRITICHE" if lev_f == "critical" else "oltre soglia"
                    lines.append(f"\n⏰ <b>PREAVVISO</b>")
                    lines.append(f"Previste raffiche {tag} fino a <b>{g_f:.0f} km/h</b> alle <b>{t_fmt}</b>")
                    lines.append(f"👉 Hai tempo per ammainare le tende")
                elif kind == "storm_now":
                    lines.append(f"\n⛈️ <b>TEMPORALE IN CORSO</b>: {WEATHER_CODE.get(payload, 'temporale')}")
                elif kind == "storm_forecast":
                    t_s, c_s = payload
                    t_fmt = t_s.strftime("%H:%M") if hasattr(t_s, "strftime") else str(t_s)
                    lines.append(f"\n⛈️ <b>TEMPORALE PREVISTO alle {t_fmt}</b>")
                    lines.append(f"Tipo: {WEATHER_CODE.get(c_s, 'temporale')}")
                elif kind == "recovery":
                    lines.append(f"\n✅ Vento rientrato nella norma (raffica {gust:.0f} km/h)")

            lines.append("")
            lines.append("<i>— Condizioni correnti —</i>")
            lines.append(f"Vento: {speed:.0f} km/h da {direction_label(wdir)}")
            lines.append(f"Raffica: <b>{gust:.0f} km/h</b>")
            lines.append(f"Cielo: {WEATHER_CODE.get(wcode, f'codice {wcode}')}")
            if temp is not None:
                lines.append(f"Temp: {temp}°C")
            if precip > 0:
                lines.append(f"Precipitazioni: {precip} mm")

            msg = "\n".join(lines)

            try:
                send_telegram(token, chat_id, msg)
                log(f"Alert inviati: {[a[0] for a in alerts]} | gust={gust:.0f}")
            except Exception as e:
                log(f"ERRORE invio Telegram: {e}")
                return 1
    else:
        log(f"OK - gust={gust:.0f} speed={speed:.0f} level={cur_level} (fcst max {max_fg:.0f})")

    # Aggiorna stato
    state["last_level"] = cur_level
    state["last_gust"] = gust
    state["last_check"] = now.strftime("%Y-%m-%d %H:%M:%S")
    state["history"] = history
    if any(a[0] == "forecast" for a in alerts):
        state["last_forecast_alert_ts"] = now.isoformat()
    if wcode in (95, 96, 99):
        state["last_storm_code"] = wcode
    else:
        state.pop("last_storm_code", None)
    state["storm_forecast_warned"] = bool(future_storms)

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

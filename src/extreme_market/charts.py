from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_episode_chart(continuous: pd.DataFrame, episode: pd.Series, output_path: str | Path, context_sessions: int = 60) -> None:
    """Draw an audit-friendly PNG with Pillow for stable Windows rendering."""
    dates = pd.to_datetime(continuous.trade_date).dt.normalize()
    start, end = pd.Timestamp(episode.event_start_date), pd.Timestamp(episode.event_end_date)
    first = max(0, int(dates.searchsorted(start)) - context_sessions)
    last = min(len(continuous), int(dates.searchsorted(end, side="right")) + context_sessions)
    view = continuous.iloc[first:last].copy().reset_index(drop=True)
    view_dates = pd.to_datetime(view.trade_date)
    width, height = 1600, 1000
    left, right, top, bottom = 90, 1540, 85, 930
    price_top, price_bottom = top + 45, 590
    volume_top, volume_bottom = 635, 760
    oi_top, oi_bottom = 805, 905
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font, label_font, small_font = _font(24, True), _font(16), _font(13)
    instrument = str(episode.get("instrument", "Instrument"))
    draw.text((left, 18), f"{instrument} {episode.episode_id} | {episode.direction} | Q1 candidate - pending review", fill="#1b2631", font=title_font)
    draw.text((left, 50), "Adjusted price path with volume, open interest, event boundaries, and 60-session context", fill="#566573", font=small_font)
    values = pd.concat([view.adjusted_low, view.adjusted_high]).astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return
    pmin, pmax = float(values.min()), float(values.max())
    if pmax <= pmin:
        pmax = pmin + 1.0
    vmax = float(view.volume.fillna(0).max()) if "volume" in view else 1.0
    omax = float(view.open_interest.fillna(0).max()) if "open_interest" in view else 1.0
    n, step = max(1, len(view)), (right - left) / max(1, len(view))
    candle_width = max(1, int(step * 0.62))

    def x_at(index: int) -> float:
        return left + (index + 0.5) * step

    def y_price(value: float) -> float:
        return price_bottom - (float(value) - pmin) / (pmax - pmin) * (price_bottom - price_top)

    def y_volume(value: float) -> float:
        return volume_bottom - (float(value) / vmax if vmax else 0) * (volume_bottom - volume_top)

    def y_oi(value: float) -> float:
        return oi_bottom - (float(value) / omax if omax else 0) * (oi_bottom - oi_top)

    for y in np.linspace(price_top, price_bottom, 5):
        draw.line((left, int(y), right, int(y)), fill="#e5e7e9", width=1)
    for y in np.linspace(volume_top, volume_bottom, 3):
        draw.line((left, int(y), right, int(y)), fill="#f0f2f3", width=1)
    for y in np.linspace(oi_top, oi_bottom, 3):
        draw.line((left, int(y), right, int(y)), fill="#f0f2f3", width=1)
    draw.text((8, price_top), "price", fill="#34495e", font=label_font)
    draw.text((8, volume_top), "volume", fill="#34495e", font=label_font)
    draw.text((8, oi_top), "open interest", fill="#34495e", font=label_font)
    event_left = left + max(0, int(dates.searchsorted(start)) - first) * step
    event_right = left + min(n, int(dates.searchsorted(end, side="right")) - first) * step
    draw.rectangle((int(event_left), price_top, int(event_right), oi_bottom), fill="#fef5e7")
    for y in np.linspace(price_top, price_bottom, 5):
        draw.line((left, int(y), right, int(y)), fill="#e5e7e9", width=1)

    for i, row in view.iterrows():
        x = x_at(i)
        o, h, low, c = [row.get(key, np.nan) for key in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close")]
        if all(pd.notna(v) for v in (o, h, low, c)):
            color = "#c0392b" if float(c) >= float(o) else "#2471a3"
            draw.line((int(x), int(y_price(h)), int(x), int(y_price(low))), fill=color, width=2)
            y1, y2 = y_price(o), y_price(c)
            draw.rectangle((int(x - candle_width / 2), int(min(y1, y2)), int(x + candle_width / 2), int(max(y1, y2) + 1)), fill=color, outline=color)
        if "volume" in view and pd.notna(row.volume):
            color = "#c0392b" if float(row.get("adjusted_close", 0)) >= float(row.get("adjusted_open", 0)) else "#2471a3"
            draw.rectangle((int(x - candle_width / 2), int(y_volume(row.volume)), int(x + candle_width / 2), volume_bottom), fill=color)
    if "open_interest" in view:
        points = [(int(x_at(i)), int(y_oi(value))) for i, value in enumerate(view.open_interest.fillna(0))]
        if len(points) > 1:
            draw.line(points, fill="#117864", width=2)
    markers = [("event_start_date", "start", "#1f618d"), ("acceleration_date", "acceleration", "#af601a"), ("extreme_point_date", "high/low", "#7d3c98"), ("event_end_date", "end", "#117864")]
    legend_x = left
    for key, label, color in markers:
        point = pd.Timestamp(episode[key])
        index = int(view_dates.searchsorted(point))
        x = x_at(min(max(index, 0), n - 1))
        draw.line((int(x), price_top, int(x), oi_bottom), fill=color, width=2)
        draw.text((legend_x, 950), label, fill=color, font=small_font)
        legend_x += 120
    for index in np.linspace(0, n - 1, min(8, n), dtype=int):
        draw.text((int(x_at(index) - 25), 915), view_dates.iloc[index].strftime("%Y-%m"), fill="#566573", font=small_font)
    draw.text((left + 760, 950), "Shaded region = candidate interval; boundaries require human review", fill="#566573", font=small_font)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)

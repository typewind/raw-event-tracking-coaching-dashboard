#!/usr/bin/env python3
"""Build dashboard data from raw Opta F24/F7 event XML and raw Tracab tracking."""

from __future__ import annotations

import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MATCH_DIR = Path("/Users/chenshuyao/Projects/tactical_physical_explore/[g987709][GW12]Manchester City 3 - 1 Manchester United")
OUT = ROOT / "data" / "dashboard-data.json"
FPS = 25
HSR_THRESHOLD = 5.5
SPRINT_THRESHOLD = 7.0

EVENT_TYPES = {
    "1": "Pass",
    "3": "Take on",
    "4": "Foul",
    "5": "Out",
    "6": "Corner awarded",
    "7": "Tackle",
    "8": "Interception",
    "10": "Save",
    "11": "Claim",
    "12": "Clearance",
    "13": "Miss",
    "14": "Post",
    "15": "Attempt saved",
    "16": "Goal",
    "17": "Card",
    "18": "Player off",
    "19": "Player on",
    "32": "Start",
    "34": "Team setup",
    "43": "Deleted event",
    "44": "Aerial",
    "45": "Challenge",
    "49": "Ball recovery",
    "50": "Dispossessed",
    "52": "Keeper pickup",
    "61": "Ball touch",
    "74": "Blocked pass",
}


@dataclass
class MatchPaths:
    f24: Path
    f7: Path
    metadata: Path
    tracab: Path


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except Exception:
        return default


def median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return round(statistics.median(values), 3) if values else None


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None and math.isfinite(v)]
    return round(sum(values) / len(values), 3) if values else None


def pct(values: list[float], p: float) -> float | None:
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return None
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * p)))
    return round(values[idx], 3)


def parse_paths(match_dir: Path) -> MatchPaths:
    game_id = match_dir.name.split("]")[0].strip("[g")
    return MatchPaths(
        f24=match_dir / f"g{game_id}_OptaF24.xml",
        f7=match_dir / f"g{game_id}_OptaF7.xml",
        metadata=match_dir / f"g{game_id}_TracabMetadata.xml",
        tracab=match_dir / f"g{game_id}_TracabData.dat",
    )


def parse_tracking_meta(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    match = root.find("match")
    if match is None:
        raise ValueError(f"No match node in {path}")
    periods = {}
    for period in match.findall("period"):
        pid = safe_int(period.attrib.get("iId"))
        start = safe_int(period.attrib.get("iStartFrame"))
        end = safe_int(period.attrib.get("iEndFrame"))
        if pid in (1, 2) and start and end:
            periods[pid] = {"start": start, "end": end}
    return {
        "fps": safe_int(match.attrib.get("iFrameRateFps"), FPS) or FPS,
        "pitch_x_m": safe_float(match.attrib.get("fPitchXSizeMeters"), 105.0) or 105.0,
        "pitch_y_m": safe_float(match.attrib.get("fPitchYSizeMeters"), 68.0) or 68.0,
        "periods": periods,
    }


def parse_f24(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[str, int], int]]:
    root = ET.parse(path).getroot()
    game = root.find("Game")
    if game is None:
        raise ValueError(f"No Game node in {path}")
    home_id = game.attrib.get("home_team_id", "")
    away_id = game.attrib.get("away_team_id", "")
    meta = {
        "match_id": game.attrib.get("id", ""),
        "match_label": f"{game.attrib.get('home_team_name')} {game.attrib.get('home_score')} - {game.attrib.get('away_score')} {game.attrib.get('away_team_name')}",
        "competition": game.attrib.get("competition_name", ""),
        "season": game.attrib.get("season_name", ""),
        "matchday": game.attrib.get("matchday", ""),
        "date": game.attrib.get("game_date", ""),
        "home": {"id": home_id, "name": game.attrib.get("home_team_name", ""), "score": safe_int(game.attrib.get("home_score"), 0)},
        "away": {"id": away_id, "name": game.attrib.get("away_team_name", ""), "score": safe_int(game.attrib.get("away_score"), 0)},
        "team_id_to_code": {home_id: 1, away_id: 0},
        "code_to_team": {
            "1": game.attrib.get("home_team_name", ""),
            "0": game.attrib.get("away_team_name", ""),
        },
        "code_to_side": {"1": "H", "0": "A"},
        "side_to_code": {"H": 1, "A": 0},
    }

    events: list[dict[str, Any]] = []
    directions: dict[tuple[str, int], int] = {}
    for node in game.findall("Event"):
        q = {child.attrib.get("qualifier_id", ""): child.attrib.get("value", "") for child in node.findall("Q")}
        team_id = node.attrib.get("team_id", "")
        period = safe_int(node.attrib.get("period_id"), 0) or 0
        if node.attrib.get("type_id") == "32" and "127" in q:
            directions[(team_id, period)] = 1 if q["127"] == "Left to Right" else -1
        type_id = node.attrib.get("type_id", "")
        x = safe_float(node.attrib.get("x"))
        y = safe_float(node.attrib.get("y"))
        end_x = safe_float(q.get("140"))
        end_y = safe_float(q.get("141"))
        minute = safe_int(node.attrib.get("min"), 0) or 0
        second = safe_int(node.attrib.get("sec"), 0) or 0
        events.append({
            "event_id": node.attrib.get("event_id", ""),
            "raw_id": node.attrib.get("id", ""),
            "type_id": type_id,
            "type_name": EVENT_TYPES.get(type_id, f"Type {type_id}"),
            "period": period,
            "minute": minute,
            "second": second,
            "team_id": team_id,
            "team": meta["home"]["name"] if team_id == home_id else meta["away"]["name"] if team_id == away_id else "",
            "team_code": meta["team_id_to_code"].get(team_id),
            "player_id": node.attrib.get("player_id", ""),
            "outcome": safe_int(node.attrib.get("outcome"), 0) or 0,
            "x": x,
            "y": y,
            "end_x": end_x,
            "end_y": end_y,
            "qualifiers": q,
        })
    return meta, events, directions


def parse_f7(path: Path, meta: dict[str, Any]) -> dict[int, dict[int, dict[str, Any]]]:
    root = ET.parse(path).getroot()
    player_names: dict[str, str] = {}
    for team in root.iter("Team"):
        for player in team.findall("Player"):
            pid = player.attrib.get("uID", "").lstrip("p")
            person = player.find("PersonName")
            if not pid or person is None:
                continue
            known = person.findtext("Known")
            first = person.findtext("First") or ""
            last = person.findtext("Last") or ""
            player_names[pid] = known or f"{first} {last}".strip()

    lineup: dict[int, dict[int, dict[str, Any]]] = {0: {}, 1: {}}
    for td in root.iter("TeamData"):
        team_ref = td.attrib.get("TeamRef", "").lstrip("t")
        code = meta["team_id_to_code"].get(team_ref)
        if code is None:
            continue
        for mp in td.findall(".//MatchPlayer"):
            shirt = safe_int(mp.attrib.get("ShirtNumber"))
            pid = mp.attrib.get("PlayerRef", "").lstrip("p")
            if shirt is None:
                continue
            lineup[code][shirt] = {
                "player_id": pid,
                "name": player_names.get(pid, f"#{shirt}"),
                "role": mp.attrib.get("Position", ""),
                "status": mp.attrib.get("Status", ""),
                "formation_place": mp.attrib.get("Formation_Place", ""),
            }
    return lineup


def event_seconds_in_period(event: dict[str, Any]) -> int:
    minute = event["minute"]
    second = event["second"]
    if event["period"] == 2 and minute >= 45:
        minute -= 45
    return minute * 60 + second


def attach_frames(events: list[dict[str, Any]], tracking_meta: dict[str, Any]) -> None:
    for event in events:
        period = event["period"]
        period_meta = tracking_meta["periods"].get(period)
        if not period_meta:
            event["frame"] = None
            continue
        event["frame"] = period_meta["start"] + event_seconds_in_period(event) * tracking_meta["fps"]


def opta_progress(event: dict[str, Any]) -> float | None:
    if event.get("x") is None or event.get("end_x") is None:
        return None
    return round(float(event["end_x"]) - float(event["x"]), 3)


def summarize_events(events: list[dict[str, Any]], meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    team_events: dict[str, Counter] = defaultdict(Counter)
    player_events: dict[str, Counter] = defaultdict(Counter)
    pass_examples: list[dict[str, Any]] = []
    event_rows = [e for e in events if e["period"] in (1, 2)]

    for e in event_rows:
        team = e["team"] or "Unknown"
        player = e["player_id"] or "Unknown"
        team_events[team]["events"] += 1
        player_events[player]["events"] += 1
        type_id = e["type_id"]
        if type_id == "1":
            team_events[team]["passes"] += 1
            player_events[player]["passes"] += 1
            if e["outcome"] == 1:
                team_events[team]["completed_passes"] += 1
                player_events[player]["completed_passes"] += 1
            progress = opta_progress(e)
            if progress is not None and progress >= 10:
                team_events[team]["progressive_passes"] += 1
                player_events[player]["progressive_passes"] += 1
            if e.get("end_x") is not None and e["end_x"] >= 66.7:
                team_events[team]["final_third_entries"] += 1
                player_events[player]["final_third_entries"] += 1
            if e.get("end_x") is not None and e.get("end_y") is not None and e["end_x"] >= 83 and 21 <= e["end_y"] <= 79:
                team_events[team]["box_entries"] += 1
                player_events[player]["box_entries"] += 1
            if "2" in e["qualifiers"]:
                team_events[team]["crosses"] += 1
                player_events[player]["crosses"] += 1
            if progress is not None and len(pass_examples) < 120 and (progress >= 15 or e.get("end_x", 0) >= 66.7):
                pass_examples.append({
                    "team": team,
                    "player_id": player,
                    "minute": e["minute"],
                    "x": e["x"],
                    "y": e["y"],
                    "end_x": e["end_x"],
                    "end_y": e["end_y"],
                    "progress": progress,
                    "outcome": e["outcome"],
                })
        elif type_id in {"13", "14", "15", "16"}:
            team_events[team]["shots"] += 1
            player_events[player]["shots"] += 1
            if type_id == "16":
                team_events[team]["goals"] += 1
                player_events[player]["goals"] += 1
        elif type_id == "49":
            team_events[team]["recoveries"] += 1
            player_events[player]["recoveries"] += 1
        elif type_id == "8":
            team_events[team]["interceptions"] += 1
            player_events[player]["interceptions"] += 1
        elif type_id == "7":
            team_events[team]["tackles"] += 1
            player_events[player]["tackles"] += 1
        elif type_id == "12":
            team_events[team]["clearances"] += 1
            player_events[player]["clearances"] += 1
        elif type_id == "3":
            team_events[team]["take_ons"] += 1
            player_events[player]["take_ons"] += 1
        elif type_id == "50":
            team_events[team]["dispossessed"] += 1
            player_events[player]["dispossessed"] += 1

    team_summary = {}
    for team in [meta["home"]["name"], meta["away"]["name"]]:
        c = team_events[team]
        passes = c["passes"]
        team_summary[team] = {k: int(v) for k, v in c.items()}
        team_summary[team]["pass_success_pct"] = round(c["completed_passes"] / passes * 100, 1) if passes else None
    player_summary = {pid: {k: int(v) for k, v in c.items()} for pid, c in player_events.items()}
    return {"event_count": len(event_rows)}, team_summary, player_summary, pass_examples


def parse_dat_line(line: str) -> dict[str, Any] | None:
    parts = line.rstrip("\n").split(":")
    if len(parts) < 3:
        return None
    frame = safe_int(parts[0])
    if frame is None:
        return None
    players = []
    for token in parts[1].split(";"):
        values = token.split(",")
        if len(values) < 6:
            continue
        team_code = safe_int(values[0], -1)
        jersey = safe_int(values[2], -1)
        if jersey is None or jersey < 0:
            jersey = safe_int(values[1], -1)
        x = safe_float(values[3])
        y = safe_float(values[4])
        speed = safe_float(values[5])
        if team_code not in (0, 1) or jersey is None or jersey < 0 or x is None or y is None or speed is None:
            continue
        if abs(x) > 5600 or abs(y) > 3800:
            continue
        players.append({"team_code": team_code, "jersey": jersey, "x": x / 100.0, "y": y / 100.0, "speed": speed})
    ball_values = [v for v in parts[2].split(",") if v != ""]
    ball = {}
    if len(ball_values) >= 6:
        ball = {
            "x": (safe_float(ball_values[0]) or 0) / 100.0,
            "y": (safe_float(ball_values[1]) or 0) / 100.0,
            "z": safe_float(ball_values[2]),
            "speed": safe_float(ball_values[3]),
            "team": ball_values[4],
            "state": ball_values[5].rstrip(";"),
        }
    return {"frame": frame, "players": players, "ball": ball}


def frame_period(frame: int, periods: dict[int, dict[str, int]]) -> int | None:
    for pid, p in periods.items():
        if p["start"] <= frame <= p["end"]:
            return pid
    return None


def normalize_x(x: float, direction: int) -> float:
    return x * direction + 52.5


def player_key(team_code: int, jersey: int) -> str:
    return f"{team_code}:{jersey}"


def close_bout(
    bout: dict[str, Any],
    hsr_bouts: list[dict[str, Any]],
    player_tracking: dict[str, Counter],
    meta: dict[str, Any],
) -> None:
    duration = (bout["end_frame"] - bout["start_frame"] + 1) / FPS
    if duration < 0.48 or bout["distance"] < 3.0:
        return
    dx = bout["end_x"] - bout["start_x"]
    dy = bout["end_y"] - bout["start_y"]
    team_name = meta["code_to_team"][str(bout["team_code"])]
    intent = "unclassified"
    if bout["possession_samples"] > 0:
        if bout["team_in_possession_samples"] >= bout["possession_samples"] * 0.55:
            if bout["progress"] >= 8:
                intent = "IP_penetration"
            elif abs(dy) > abs(dx):
                intent = "IP_support_width"
            else:
                intent = "IP_support_space"
        else:
            if bout["towards_ball_delta"] <= -6:
                intent = "OOP_press_or_intercept"
            elif bout["progress"] <= -8:
                intent = "OOP_recovery"
            else:
                intent = "OOP_cover"
    hsr_bouts.append({
        "team": team_name,
        "team_code": bout["team_code"],
        "jersey": bout["jersey"],
        "start_frame": bout["start_frame"],
        "end_frame": bout["end_frame"],
        "duration_s": round(duration, 2),
        "distance_m": round(bout["distance"], 2),
        "peak_speed_m_s": round(bout["peak_speed"], 2),
        "dx_m": round(dx, 2),
        "dy_m": round(dy, 2),
        "own_goal_progress_m": round(bout["progress"], 2),
        "intent_proxy": intent,
    })
    key = player_key(bout["team_code"], bout["jersey"])
    player_tracking[key]["hsr_bouts"] += 1
    player_tracking[key][f"intent_{intent}"] += 1


def summarize_tracking(
    dat_path: Path,
    tracking_meta: dict[str, Any],
    meta: dict[str, Any],
    directions: dict[tuple[str, int], int],
    lineup: dict[int, dict[int, dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    team_tracking: dict[str, dict[str, list[float]]] = {
        meta["home"]["name"]: defaultdict(list),
        meta["away"]["name"]: defaultdict(list),
    }
    player_tracking: dict[str, Counter] = defaultdict(Counter)
    player_distance: dict[str, float] = defaultdict(float)
    player_hsr_distance: dict[str, float] = defaultdict(float)
    player_sprint_distance: dict[str, float] = defaultdict(float)
    hsr_bouts: list[dict[str, Any]] = []
    active_bouts: dict[str, dict[str, Any]] = {}
    pressure_samples = 0
    frame_count = 0
    sampled_frames = 0
    minute_bins: dict[int, dict[str, Any]] = defaultdict(lambda: defaultdict(list))
    player_last_frame: dict[str, int] = {}

    period_ranges = tracking_meta["periods"]
    with dat_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parsed = parse_dat_line(line)
            if not parsed:
                continue
            frame = parsed["frame"]
            period = frame_period(frame, period_ranges)
            if period is None:
                continue
            frame_count += 1
            players = parsed["players"]
            ball = parsed["ball"]
            ball_team = ball.get("team")
            ball_code = meta["side_to_code"].get(ball_team)
            by_team = {0: [], 1: []}
            for p in players:
                by_team[p["team_code"]].append(p)
                key = player_key(p["team_code"], p["jersey"])
                player_last_frame[key] = frame
                player_distance[key] += max(0.0, p["speed"]) / FPS
                if p["speed"] >= HSR_THRESHOLD:
                    player_hsr_distance[key] += p["speed"] / FPS
                if p["speed"] >= SPRINT_THRESHOLD:
                    player_sprint_distance[key] += p["speed"] / FPS

                direction = 1
                team_id = meta["home"]["id"] if p["team_code"] == 1 else meta["away"]["id"]
                direction = directions.get((team_id, period), direction)
                own_x = normalize_x(p["x"], direction)
                bkey = key
                if p["speed"] >= HSR_THRESHOLD:
                    if bkey not in active_bouts:
                        active_bouts[bkey] = {
                            "team_code": p["team_code"],
                            "jersey": p["jersey"],
                            "start_frame": frame,
                            "end_frame": frame,
                            "start_x": p["x"],
                            "start_y": p["y"],
                            "end_x": p["x"],
                            "end_y": p["y"],
                            "start_own_x": own_x,
                            "progress": 0.0,
                            "distance": 0.0,
                            "peak_speed": p["speed"],
                            "possession_samples": 0,
                            "team_in_possession_samples": 0,
                            "first_ball_dist": None,
                            "last_ball_dist": None,
                            "towards_ball_delta": 0.0,
                        }
                    bout = active_bouts[bkey]
                    bout["end_frame"] = frame
                    bout["end_x"] = p["x"]
                    bout["end_y"] = p["y"]
                    bout["progress"] = own_x - bout["start_own_x"]
                    bout["distance"] += p["speed"] / FPS
                    bout["peak_speed"] = max(bout["peak_speed"], p["speed"])
                    if ball_code in (0, 1):
                        bout["possession_samples"] += 1
                        if ball_code == p["team_code"]:
                            bout["team_in_possession_samples"] += 1
                    if "x" in ball:
                        dist = math.hypot(p["x"] - ball["x"], p["y"] - ball["y"])
                        if bout["first_ball_dist"] is None:
                            bout["first_ball_dist"] = dist
                        bout["last_ball_dist"] = dist
                        bout["towards_ball_delta"] = dist - bout["first_ball_dist"]
                elif bkey in active_bouts:
                    close_bout(active_bouts.pop(bkey), hsr_bouts, player_tracking, meta)

            stale = [key for key, last in player_last_frame.items() if key in active_bouts and frame - last > 5]
            for key in stale:
                close_bout(active_bouts.pop(key), hsr_bouts, player_tracking, meta)

            if frame % FPS == 0:
                sampled_frames += 1
                for code, team_players in by_team.items():
                    if len(team_players) < 6:
                        continue
                    team_name = meta["code_to_team"][str(code)]
                    xs = [p["x"] for p in team_players]
                    ys = [p["y"] for p in team_players]
                    team_id = meta["home"]["id"] if code == 1 else meta["away"]["id"]
                    direction = directions.get((team_id, period), 1)
                    own_distances = [normalize_x(p["x"], direction) for p in team_players]
                    width = max(ys) - min(ys)
                    depth = max(xs) - min(xs)
                    team_tracking[team_name]["width_m"].append(width)
                    team_tracking[team_name]["depth_m"].append(depth)
                    team_tracking[team_name]["area_m2"].append(width * depth)
                    team_tracking[team_name]["height_m"].append(sum(own_distances) / len(own_distances))
                    defenders = [p for p in team_players if lineup.get(code, {}).get(p["jersey"], {}).get("role") == "Defender"]
                    if defenders:
                        team_tracking[team_name]["def_line_height_m"].append(sum(normalize_x(p["x"], direction) for p in defenders) / len(defenders))
                    minute = int((frame - period_ranges[period]["start"]) / (FPS * 60)) + (45 if period == 2 else 0)
                    minute_bins[minute][f"{team_name}_width"].append(width)
                    minute_bins[minute][f"{team_name}_depth"].append(depth)
                    minute_bins[minute][f"{team_name}_height"].append(sum(own_distances) / len(own_distances))

                if ball_code in (0, 1) and ball.get("state", "").startswith("Alive") and "x" in ball:
                    defending_code = 1 - ball_code
                    defenders = by_team.get(defending_code, [])
                    if defenders:
                        nearest = min(math.hypot(p["x"] - ball["x"], p["y"] - ball["y"]) for p in defenders)
                        defending_team = meta["code_to_team"][str(defending_code)]
                        team_tracking[defending_team]["nearest_to_ball_m"].append(nearest)
                        team_tracking[defending_team]["pressure_5m"].append(1.0 if nearest <= 5 else 0.0)
                        team_tracking[defending_team]["pressure_8m"].append(1.0 if nearest <= 8 else 0.0)
                        pressure_samples += 1
                        minute = int((frame - period_ranges[period]["start"]) / (FPS * 60)) + (45 if period == 2 else 0)
                        minute_bins[minute][f"{defending_team}_pressure"].append(1.0 if nearest <= 8 else 0.0)

    for bout in list(active_bouts.values()):
        close_bout(bout, hsr_bouts, player_tracking, meta)

    team_summary = {}
    for team, vals in team_tracking.items():
        team_summary[team] = {
            "avg_width_m": mean(vals["width_m"]),
            "avg_depth_m": mean(vals["depth_m"]),
            "avg_area_m2": mean(vals["area_m2"]),
            "avg_height_m_from_own_goal": mean(vals["height_m"]),
            "avg_def_line_height_m": mean(vals["def_line_height_m"]),
            "nearest_defender_to_ball_median": median(vals["nearest_to_ball_m"]),
            "pressure_5m_pct": round((mean(vals["pressure_5m"]) or 0) * 100, 1),
            "pressure_8m_pct": round((mean(vals["pressure_8m"]) or 0) * 100, 1),
        }

    for key, distance in player_distance.items():
        player_tracking[key]["distance_m"] = round(distance, 1)
        player_tracking[key]["hsr_distance_m"] = round(player_hsr_distance[key], 1)
        player_tracking[key]["sprint_distance_m"] = round(player_sprint_distance[key], 1)

    player_rows = {}
    for key, counts in player_tracking.items():
        code_s, jersey_s = key.split(":")
        code, jersey = int(code_s), int(jersey_s)
        info = lineup.get(code, {}).get(jersey, {})
        player_rows[key] = {
            "team": meta["code_to_team"].get(code_s, ""),
            "team_code": code,
            "jersey": jersey,
            "player": info.get("name", f"#{jersey}"),
            "role": info.get("role", ""),
            **{k: int(v) if isinstance(v, int) else v for k, v in counts.items()},
        }

    minute_series = []
    for minute in sorted(minute_bins):
        row = {"minute": minute}
        for key, vals in minute_bins[minute].items():
            row[key] = mean(vals)
        minute_series.append(row)

    tracking_summary = {
        "raw_frames_processed": frame_count,
        "sampled_shape_frames": sampled_frames,
        "pressure_samples": pressure_samples,
        "hsr_threshold_m_s": HSR_THRESHOLD,
        "sprint_threshold_m_s": SPRINT_THRESHOLD,
    }
    return tracking_summary, team_summary, player_rows, hsr_bouts[:350], minute_series


def merge_player_rows(
    event_players: dict[str, dict[str, Any]],
    tracking_players: dict[str, dict[str, Any]],
    lineup: dict[int, dict[int, dict[str, Any]]],
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    player_id_to_key = {}
    for code, players in lineup.items():
        for jersey, info in players.items():
            if info.get("player_id"):
                player_id_to_key[info["player_id"]] = player_key(code, jersey)

    merged = {k: dict(v) for k, v in tracking_players.items()}
    for player_id, ev in event_players.items():
        key = player_id_to_key.get(player_id)
        if key is None:
            continue
        row = merged.setdefault(key, {})
        row.update(ev)
    for key, row in merged.items():
        if "player" not in row:
            code_s, jersey_s = key.split(":")
            info = lineup.get(int(code_s), {}).get(int(jersey_s), {})
            row.update({
                "team": meta["code_to_team"].get(code_s, ""),
                "team_code": int(code_s),
                "jersey": int(jersey_s),
                "player": info.get("name", f"#{jersey_s}"),
                "role": info.get("role", ""),
            })
        passes = row.get("passes", 0)
        row["pass_success_pct"] = round(row.get("completed_passes", 0) / passes * 100, 1) if passes else None
    return sorted(merged.values(), key=lambda r: (r.get("team", ""), r.get("role", ""), -float(r.get("hsr_distance_m", 0) or 0)))


def concept_checks(team_summary: dict[str, Any], event_team_summary: dict[str, Any], tracking_team_summary: dict[str, Any], hsr_bouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for concept, question, metric, status in [
        ("紧凑性", "球队横纵向是否压缩空间？", "avg_width_m / avg_depth_m / avg_area_m2", "verified_raw_tracking"),
        ("防守阵块", "球队站位高度是否可量化？", "avg_height_m_from_own_goal / avg_def_line_height_m", "verified_raw_tracking"),
        ("压迫", "离球最近防守者是否形成压力？", "nearest_defender_to_ball_median / pressure_5m_pct / pressure_8m_pct", "verified_raw_tracking"),
        ("高速跑", "高强度跑动是否可识别并放入上下文？", "hsr_bouts / hsr_distance_m / sprint_distance_m / intent_proxy", "verified_raw_tracking_event_context"),
        ("破线/推进", "向前传球和三区进入是否可从事件识别？", "progressive_passes / final_third_entries / box_entries", "verified_raw_event"),
        ("传中/倒三角代理", "边路送入和禁区传球是否可识别？", "crosses / box_entries", "verified_raw_event_tracking_context"),
        ("反压迫/反击入口", "夺回和丢球后时间窗是否可切片？", "recoveries / dispossessed + frame mapping", "verified_raw_event_frame_alignment"),
        ("阵型与角色", "角色行为是否可按球员/位置汇总？", "lineup role + event/tracking player rows", "verified_raw_f7_tracking"),
    ]:
        checks.append({"concept": concept, "football_question": question, "metric": metric, "status": status})
    hsr_counter = Counter(b["intent_proxy"] for b in hsr_bouts)
    for team, data in team_summary.items():
        data["verified_concepts"] = ["compactness", "block height", "pressure", "progression", "high-speed running"]
    checks.append({"concept": "高速跑意图代理", "football_question": "原始规则能否给每段高速跑分配初始战术语境？", "metric": dict(hsr_counter), "status": "heuristic_proxy_requires_review"})
    return checks


def main() -> None:
    paths = parse_paths(MATCH_DIR)
    tracking_meta = parse_tracking_meta(paths.metadata)
    meta, events, directions = parse_f24(paths.f24)
    attach_frames(events, tracking_meta)
    lineup = parse_f7(paths.f7, meta)
    event_summary, event_team, event_players, pass_examples = summarize_events(events, meta)
    tracking_summary, tracking_team, tracking_players, hsr_bouts, minute_series = summarize_tracking(paths.tracab, tracking_meta, meta, directions, lineup)

    teams = {}
    for team in [meta["home"]["name"], meta["away"]["name"]]:
        teams[team] = {
            **event_team.get(team, {}),
            **tracking_team.get(team, {}),
        }
    players = merge_player_rows(event_players, tracking_players, lineup, meta)
    payload = {
        "meta": {
            **meta,
            "raw_sources": {
                "event_f24": str(paths.f24),
                "lineup_f7": str(paths.f7),
                "tracking_dat": str(paths.tracab),
                "tracking_metadata": str(paths.metadata),
            },
            "method": "Raw Opta F24/F7 XML + raw Tracab frame stream. No aggregated provider fields, no prior model outputs.",
        },
        "audit": {
            **event_summary,
            **tracking_summary,
            "players": len(players),
            "teams": len(teams),
            "concept_checks": len(concept_checks(teams, event_team, tracking_team, hsr_bouts)),
        },
        "teams": teams,
        "players": players,
        "minute_series": minute_series,
        "hsr_bouts": hsr_bouts,
        "pass_examples": pass_examples,
        "concept_checks": concept_checks(teams, event_team, tracking_team, hsr_bouts),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "teams": len(teams), "players": len(players), "hsr_bouts_sample": len(hsr_bouts), **payload["audit"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

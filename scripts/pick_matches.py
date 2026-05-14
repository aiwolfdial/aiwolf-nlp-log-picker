#!/usr/bin/env python3
"""Pick optimal AIWolf match logs from per-track folders using ILP.

Input layout:
    data/{track_name}/*.log

Outputs:
    selected/{track_name}/*.log     copies of chosen logs
    table/{track_name}/*.csv|xlsx   role distribution, summary, selected matches
"""

import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import pulp


TARGET_ROLES = {"BODYGUARD", "MEDIUM", "POSSESSED", "SEER", "VILLAGER", "WEREWOLF"}


@dataclass
class OptimizationResult:
    selected_indices: List[int]
    selected_files: List[str]
    team_participation: Dict[str, int]
    team_role_counts: Dict[str, Dict[str, int]]
    total_matches: int
    balance_score: float
    optimization_status: str


def normalize_team_name(team_name: str) -> str:
    return re.sub(r"-[A-Za-z]\d+$", "", team_name)


def list_log_files(track_dir: str) -> List[str]:
    files = [f for f in os.listdir(track_dir) if f.endswith(".log")]

    def sort_key(name: str):
        m = re.search(r"(\d+)", name)
        return (int(m.group(1)) if m else 0, name)

    files.sort(key=sort_key)
    return files


def parse_log_file(path: str) -> List[Tuple[str, str]]:
    """Return [(role, normalized_team), ...] from the initial day-0 status block.

    The initial status block ends at the first non-status row after at least one
    status row has been seen.
    """
    assignments: List[Tuple[str, str]] = []
    started = False
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 7 and parts[1] == "status":
                started = True
                role = parts[3]
                team = normalize_team_name(parts[5])
                if role in TARGET_ROLES:
                    assignments.append((role, team))
            elif started:
                break
    return assignments


def derive_role_num_map(assignments: List[Tuple[str, str]]) -> Dict[str, int]:
    """Count occurrences of each target role in one match's initial status block."""
    counts: Dict[str, int] = {r: 0 for r in TARGET_ROLES}
    for role, _ in assignments:
        if role in counts:
            counts[role] += 1
    return counts


def build_pattern_data(track_dir: str, log_files: List[str]):
    """Parse logs; return per-match patterns, team mapping, role_num_map, player_counts."""
    team_to_idx: Dict[str, int] = {}
    pattern_of_matches: List[Dict[str, List[int]]] = []
    role_num_map: Dict[str, int] = None
    player_counts: List[int] = []

    for log_file in log_files:
        assignments = parse_log_file(os.path.join(track_dir, log_file))
        entry: Dict[str, List[int]] = {r: [] for r in TARGET_ROLES}
        for role, team in assignments:
            if team not in team_to_idx:
                team_to_idx[team] = len(team_to_idx)
            ti = team_to_idx[team]
            if ti not in entry[role]:
                entry[role].append(ti)
        for r in entry:
            entry[r].sort()
        pattern_of_matches.append(entry)
        player_counts.append(len(assignments))
        if role_num_map is None and assignments:
            role_num_map = derive_role_num_map(assignments)

    idx_to_team = {idx: team for team, idx in team_to_idx.items()}
    if role_num_map is None:
        role_num_map = {r: 0 for r in TARGET_ROLES}
    return pattern_of_matches, idx_to_team, role_num_map, player_counts


def solve_ilp(
    pattern_of_matches: List[Dict[str, List[int]]],
    idx_to_team: Dict[int, str],
    role_num_map: Dict[str, int],
    target_matches: int = None,
    max_zero_roles_per_team: int = 0,
    count_only_seen_roles: bool = True,
    require_min_participation: bool = True,
    balance_weight: float = 1.0,
) -> OptimizationResult:
    n_matches = len(pattern_of_matches)
    n_teams = len(idx_to_team)
    roles = list(role_num_map.keys())

    if target_matches is None:
        target_matches = max(1, n_matches // 2)

    participation = np.zeros((n_matches, n_teams), dtype=int)
    role_matrices: Dict[str, np.ndarray] = {
        r: np.zeros((n_matches, n_teams), dtype=int) for r in roles
    }
    for m, match in enumerate(pattern_of_matches):
        playing = set()
        for role, idxs in match.items():
            if role not in role_matrices:
                continue
            for ti in idxs:
                if 0 <= ti < n_teams:
                    role_matrices[role][m, ti] = 1
                    playing.add(ti)
        for ti in playing:
            participation[m, ti] = 1

    prob = pulp.LpProblem("Match_Selection", pulp.LpMinimize)

    match_vars = {
        i: pulp.LpVariable(f"match_{i}", cat="Binary") for i in range(n_matches)
    }
    team_part = {
        ti: pulp.LpVariable(f"part_{ti}", lowBound=0, cat="Integer")
        for ti in range(n_teams)
    }
    team_role = {
        ti: {
            r: pulp.LpVariable(f"team_{ti}_role_{r}", lowBound=0, cat="Integer")
            for r in roles
        }
        for ti in range(n_teams)
    }

    prob += pulp.lpSum(match_vars.values()) == target_matches

    for ti in range(n_teams):
        prob += team_part[ti] == pulp.lpSum(
            participation[m, ti] * match_vars[m] for m in range(n_matches)
        )
        for r in roles:
            prob += team_role[ti][r] == pulp.lpSum(
                role_matrices[r][m, ti] * match_vars[m] for m in range(n_matches)
            )

    seen = {
        (ti, r): any(role_matrices[r][m, ti] == 1 for m in range(n_matches))
        for ti in range(n_teams)
        for r in roles
    }
    w_vars: Dict[int, Dict[str, pulp.LpVariable]] = {ti: {} for ti in range(n_teams)}
    BIG_M = n_matches
    for ti in range(n_teams):
        for r in roles:
            if role_num_map.get(r, 0) <= 0:
                continue
            if count_only_seen_roles and not seen[(ti, r)]:
                continue
            w = pulp.LpVariable(f"w_{ti}_{r}", cat="Binary")
            w_vars[ti][r] = w
            y = team_role[ti][r]
            prob += y >= w
            prob += y <= BIG_M * w

    if max_zero_roles_per_team is not None:
        for ti in range(n_teams):
            if w_vars[ti]:
                prob += (
                    pulp.lpSum(1 - w_vars[ti][r] for r in w_vars[ti])
                    <= max_zero_roles_per_team
                )

    if require_min_participation:
        for ti in range(n_teams):
            prob += team_part[ti] >= 1

    max_p = pulp.LpVariable("max_p", lowBound=0, cat="Integer")
    min_p = pulp.LpVariable("min_p", lowBound=0, cat="Integer")
    for ti in range(n_teams):
        prob += max_p >= team_part[ti]
        prob += min_p <= team_part[ti]

    role_spread = {}
    for r in roles:
        if role_num_map.get(r, 0) > 0:
            mx = pulp.LpVariable(f"max_{r}", lowBound=0, cat="Integer")
            mn = pulp.LpVariable(f"min_{r}", lowBound=0, cat="Integer")
            role_spread[r] = (mx, mn)
            for ti in range(n_teams):
                prob += mx >= team_role[ti][r]
                prob += mn <= team_role[ti][r]

    objective = (max_p - min_p) * balance_weight
    for r, (mx, mn) in role_spread.items():
        weight = role_num_map[r] if role_num_map[r] > 0 else 1
        objective += (mx - mn) * weight * balance_weight
    prob += objective

    print(f"Solving ILP for {target_matches} matches...")
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[prob.status]

    selected_indices: List[int] = []
    team_participation_out: Dict[str, int] = {}
    team_role_out: Dict[str, Dict[str, int]] = {}

    if prob.status == pulp.LpStatusOptimal:
        selected_indices = [
            i for i in range(n_matches) if pulp.value(match_vars[i]) == 1
        ]

    for ti in range(n_teams):
        team_name = idx_to_team[ti]
        if prob.status == pulp.LpStatusOptimal:
            team_participation_out[team_name] = int(pulp.value(team_part[ti]))
            team_role_out[team_name] = {
                r: int(pulp.value(team_role[ti][r])) for r in roles
            }
        else:
            team_participation_out[team_name] = 0
            team_role_out[team_name] = {r: 0 for r in roles}

    score = (
        float(pulp.value(prob.objective))
        if prob.status == pulp.LpStatusOptimal
        else float("inf")
    )

    return OptimizationResult(
        selected_indices=selected_indices,
        selected_files=[],
        team_participation=team_participation_out,
        team_role_counts=team_role_out,
        total_matches=len(selected_indices),
        balance_score=score,
        optimization_status=status,
    )


def display_result(result: OptimizationResult, role_num_map: Dict[str, int]) -> None:
    print("\n=== Optimization Results ===")
    print(f"Status: {result.optimization_status}")
    print(f"Selected matches: {result.total_matches}")
    print(f"Balance score: {result.balance_score:.2f}")

    print("\n=== Team Participation ===")
    for team, count in sorted(result.team_participation.items()):
        print(f"  {team}: {count}")

    parts = list(result.team_participation.values())
    if parts:
        print(
            f"  Mean={np.mean(parts):.2f}  Std={np.std(parts):.2f}  "
            f"Min={min(parts)}  Max={max(parts)}"
        )

    print("\n=== Role Distribution ===")
    rows = []
    for team in sorted(result.team_role_counts):
        row = {"Team": team, **result.team_role_counts[team]}
        row["Total"] = result.team_participation[team]
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n=== Role Balance ===")
    for role in role_num_map:
        if role_num_map.get(role, 0) > 0:
            counts = [result.team_role_counts[t][role] for t in result.team_role_counts]
            print(
                f"  {role}: Mean={np.mean(counts):.2f}  Std={np.std(counts):.2f}  "
                f"Min={min(counts)}  Max={max(counts)}"
            )


def save_outputs(
    result: OptimizationResult,
    track_name: str,
    track_dir: str,
    log_files: List[str],
    root_dir: str,
) -> None:
    selected_files = [log_files[i] for i in result.selected_indices]
    result.selected_files = selected_files

    out_dir = os.path.join(root_dir, "selected", track_name)
    os.makedirs(out_dir, exist_ok=True)
    for name in selected_files:
        shutil.copy2(os.path.join(track_dir, name), os.path.join(out_dir, name))
    print(f"\nCopied {len(selected_files)} logs to {out_dir}")

    table_dir = os.path.join(root_dir, "table", track_name)
    os.makedirs(table_dir, exist_ok=True)

    rows = []
    for team in sorted(result.team_role_counts):
        row = {"Team": team, **result.team_role_counts[team]}
        row["Total_Participation"] = result.team_participation[team]
        rows.append(row)
    df = pd.DataFrame(rows)
    csv_path = os.path.join(table_dir, f"role_distribution_{track_name}.csv")
    df.to_csv(csv_path, index=False)
    print(f"Saved: {csv_path}")
    try:
        xlsx_path = os.path.join(table_dir, f"role_distribution_{track_name}.xlsx")
        df.to_excel(xlsx_path, index=False)
        print(f"Saved: {xlsx_path}")
    except ImportError:
        pass

    parts = list(result.team_participation.values())
    summary_df = pd.DataFrame(
        {
            "Metric": [
                "Total Matches Selected",
                "Balance Score",
                "Optimization Status",
                "Mean Team Participation",
                "Std Dev Team Participation",
                "Min Team Participation",
                "Max Team Participation",
            ],
            "Value": [
                result.total_matches,
                f"{result.balance_score:.2f}",
                result.optimization_status,
                f"{np.mean(parts):.2f}" if parts else "0.00",
                f"{np.std(parts):.2f}" if parts else "0.00",
                min(parts) if parts else 0,
                max(parts) if parts else 0,
            ],
        }
    )
    summary_path = os.path.join(table_dir, f"optimization_summary_{track_name}.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"Saved: {summary_path}")

    matches_df = pd.DataFrame(
        {
            "Selected_Match_Index": result.selected_indices,
            "Log_File": selected_files,
        }
    )
    matches_path = os.path.join(table_dir, f"selected_matches_{track_name}.csv")
    matches_df.to_csv(matches_path, index=False)
    print(f"Saved: {matches_path}")


def prompt_choice(prompt: str, choices: List[str]) -> int:
    while True:
        try:
            raw = input(prompt).strip()
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return idx
        except (ValueError, EOFError):
            pass
        print(f"Please enter a number between 1 and {len(choices)}")


def main() -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, ".."))
    data_dir = os.path.join(root_dir, "data")

    if not os.path.isdir(data_dir):
        print(f"data directory not found: {data_dir}")
        return 1

    tracks = []
    for name in sorted(os.listdir(data_dir)):
        full = os.path.join(data_dir, name)
        if not os.path.isdir(full):
            continue
        if any(f.endswith(".log") for f in os.listdir(full)):
            tracks.append(name)

    if not tracks:
        print("No track folder with .log files found under data/")
        print("Place .log files at data/{track_name}/*.log")
        return 1

    print("=== AIWolf Log Picker ===\n")
    print("Available tracks:")
    for i, t in enumerate(tracks, 1):
        n = sum(1 for f in os.listdir(os.path.join(data_dir, t)) if f.endswith(".log"))
        print(f"  {i}. {t} ({n} logs)")

    choice = prompt_choice(f"\nSelect track (1-{len(tracks)}): ", tracks)
    track = tracks[choice - 1]
    track_dir = os.path.join(data_dir, track)

    log_files = list_log_files(track_dir)
    print(f"\nFound {len(log_files)} log files in {track_dir}")

    pattern_of_matches, idx_to_team, role_num_map, player_counts = build_pattern_data(
        track_dir, log_files
    )

    unique_counts = sorted(set(player_counts))
    if len(unique_counts) > 1:
        print(
            f"Warning: inconsistent player counts across logs: {unique_counts}. "
            f"Using {player_counts[0]} from the first log for role weights."
        )
    print(f"Detected player count: {player_counts[0]}")
    print(
        "Role composition: "
        + ", ".join(f"{r}={n}" for r, n in role_num_map.items() if n > 0)
    )
    print(f"Detected {len(idx_to_team)} teams: {', '.join(idx_to_team.values())}")

    try:
        raw = input("\nTarget number of matches (Enter for default): ").strip()
        target_matches = int(raw) if raw else None
        raw = input(
            "Max zero-count roles per team (0=forbid, 1=allow one, ...; Enter=0): "
        ).strip()
        max_zero_roles_per_team = int(raw) if raw else 0
        raw = input("Count only roles seen in data for each team? [Y/n]: ").strip().lower()
        count_only_seen_roles = raw != "n"
        raw = input("Require each team to appear at least once? [Y/n]: ").strip().lower()
        require_min_participation = raw != "n"
    except (ValueError, EOFError):
        print("Using defaults")
        target_matches = None
        max_zero_roles_per_team = 0
        count_only_seen_roles = True
        require_min_participation = True

    result = solve_ilp(
        pattern_of_matches=pattern_of_matches,
        idx_to_team=idx_to_team,
        role_num_map=role_num_map,
        target_matches=target_matches,
        max_zero_roles_per_team=max_zero_roles_per_team,
        count_only_seen_roles=count_only_seen_roles,
        require_min_participation=require_min_participation,
    )

    display_result(result, role_num_map)

    if result.total_matches > 0:
        save_outputs(result, track, track_dir, log_files, root_dir)

    return 0


if __name__ == "__main__":
    exit(main())

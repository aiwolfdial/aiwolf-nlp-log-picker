#!/usr/bin/env python3
import json
import os
import numpy as np
from typing import Dict, List
import pulp  # Integer Linear Programming
from dataclasses import dataclass
import pandas as pd
import shutil

@dataclass
class OptimizationResult:
    """Results from the match selection optimization"""
    selected_matches: List[int]
    team_participation: Dict[str, int]
    team_role_counts: Dict[str, Dict[str, int]]
    total_matches: int
    balance_score: float
    optimization_status: str

class MatchSelectionOptimizer:
    def __init__(self, pattern_file_path: str):
        """Initialize optimizer with pattern of matches data"""
        self.pattern_file_path = pattern_file_path
        self.data = None
        self.idx_team_map = {}
        self.role_num_map = {}
        self.pattern_of_matches = []
        self.teams = []
        self.roles = []
        self.dataset_name = None

        self.load_pattern_data()

    def load_pattern_data(self):
        """Load pattern of matches data from JSON file"""
        if not os.path.exists(self.pattern_file_path):
            raise FileNotFoundError(f"Pattern file not found: {self.pattern_file_path}")

        with open(self.pattern_file_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        self.idx_team_map = self.data['idx_team_map']
        self.role_num_map = self.data['role_num_map']
        self.pattern_of_matches = self.data['pattern_of_matches']

        self.teams = list(self.idx_team_map.values())
        self.roles = list(self.role_num_map.keys())

        # Extract dataset name from pattern file path
        # e.g. "data/pattern_of_matches/foo/pattern_of_matches.json" -> "foo"
        path_parts = self.pattern_file_path.replace('\\', '/').split('/')
        if 'pattern_of_matches' in path_parts:
            pattern_idx = path_parts.index('pattern_of_matches')
            if pattern_idx + 1 < len(path_parts):
                self.dataset_name = path_parts[pattern_idx + 1]
            else:
                basename = os.path.basename(self.pattern_file_path)
                self.dataset_name = basename.replace('pattern_of_matches_', '').replace('.json', '')
        else:
            basename = os.path.basename(self.pattern_file_path)
            self.dataset_name = basename.replace('pattern_of_matches_', '').replace('.json', '')

        print(f"Loaded {len(self.pattern_of_matches)} matches with {len(self.teams)} teams")
        print(f"Teams: {', '.join(self.teams)}")
        print(f"Roles: {', '.join(self.roles)}")

    def calculate_participation_matrix(self) -> np.ndarray:
        """Calculate team participation matrix (matches x teams)"""
        n_matches = len(self.pattern_of_matches)
        n_teams = len(self.teams)

        participation_matrix = np.zeros((n_matches, n_teams), dtype=int)

        for match_idx, match_data in enumerate(self.pattern_of_matches):
            participating_teams = set()
            for role, team_indices in match_data.items():
                participating_teams.update(team_indices)

            for team_idx in participating_teams:
                if team_idx < n_teams:  # Ensure valid team index
                    participation_matrix[match_idx, team_idx] = 1

        return participation_matrix

    def calculate_role_assignment_matrix(self) -> Dict[str, np.ndarray]:
        """Calculate role assignment matrices (matches x teams) for each role"""
        n_matches = len(self.pattern_of_matches)
        n_teams = len(self.teams)

        role_matrices = {}
        for role in self.roles:
            role_matrices[role] = np.zeros((n_matches, n_teams), dtype=int)

        for match_idx, match_data in enumerate(self.pattern_of_matches):
            for role, team_indices in match_data.items():
                if role in role_matrices:
                    for team_idx in team_indices:
                        if team_idx < n_teams:  # Ensure valid team index
                            role_matrices[role][match_idx, team_idx] = 1

        return role_matrices

    def solve_ilp_optimization(
        self,
        target_matches: int = None,
        balance_weight: float = 1.0,
        max_zero_roles_per_team: int = 0,
        count_only_seen_roles: bool = True,
        require_min_participation: bool = True
    ) -> OptimizationResult:
        """
        Solve optimization using Integer Linear Programming with extra constraints:

        - max_zero_roles_per_team: 各チームの「担当回数0の役職」の上限（0=禁止, 1=1役職まで, ...）
          ※ count_only_seen_roles=True のとき、データ上一度も担当していない(t,r)は“0回”の計算に含めない
        - require_min_participation: True のとき各チームの総出場 >= 1 を強制
        """
        n_matches = len(self.pattern_of_matches)
        n_teams = len(self.teams)

        if target_matches is None:
            target_matches = max(1, n_matches // 2)

        # Create ILP problem
        prob = pulp.LpProblem("Match_Selection_Optimization", pulp.LpMinimize)

        # Decision variables: binary variable for each match
        match_vars = {i: pulp.LpVariable(f"match_{i}", cat='Binary') for i in range(n_matches)}

        # Auxiliary variables for participation & role counts
        team_participation_vars = {}
        team_role_vars = {}
        for team_idx in range(n_teams):
            team_participation_vars[team_idx] = pulp.LpVariable(
                f"team_participation_{team_idx}", lowBound=0, cat='Integer'
            )
            team_role_vars[team_idx] = {}
            for role in self.roles:
                team_role_vars[team_idx][role] = pulp.LpVariable(
                    f"team_{team_idx}_role_{role}", lowBound=0, cat='Integer'
                )

        # Matrices
        participation_matrix = self.calculate_participation_matrix()
        role_matrices = self.calculate_role_assignment_matrix()

        # Constraint 1: exactly target number of matches
        prob += pulp.lpSum([match_vars[i] for i in range(n_matches)]) == target_matches

        # Constraint 2: team participation calculation
        for team_idx in range(n_teams):
            prob += team_participation_vars[team_idx] == pulp.lpSum([
                participation_matrix[m, team_idx] * match_vars[m] for m in range(n_matches)
            ])

        # Constraint 3: role assignment calculation
        for team_idx in range(n_teams):
            for role in self.roles:
                prob += team_role_vars[team_idx][role] == pulp.lpSum([
                    role_matrices[role][m, team_idx] * match_vars[m] for m in range(n_matches)
                ])

        # ----- New constraints: control "zero-count roles" per team -----
        # 判定: その(t,r)がデータ上一度でも発生しているか（見たことがある役職担当か）
        seen = {}
        for team_idx in range(n_teams):
            for role in self.roles:
                seen[(team_idx, role)] = any(role_matrices[role][m, team_idx] == 1 for m in range(n_matches))

        # w[t][r] = 1 なら「役職rを1回以上担当」、0なら「0回」
        w_vars = {team_idx: {} for team_idx in range(n_teams)}
        BIG_M = n_matches  # 十分大きい上限

        for team_idx in range(n_teams):
            for role in self.roles:
                # 採用していない役職（role_num_map==0）は対象外
                if self.role_num_map.get(role, 0) <= 0:
                    continue
                # 見かけたことがない(t,r)をゼロ計数から外す場合はスキップ
                if count_only_seen_roles and not seen[(team_idx, role)]:
                    continue

                w = pulp.LpVariable(f"w_team_{team_idx}_role_{role}", cat='Binary')
                w_vars[team_idx][role] = w
                y = team_role_vars[team_idx][role]
                # w=1 → y>=1, w=0 → y<=0
                prob += y >= w  # y >= 1*w
                prob += y <= BIG_M * w

        # 各チームの「0回役職数」の上限
        if max_zero_roles_per_team is not None:
            for team_idx in range(n_teams):
                if w_vars[team_idx]:  # 対象役職がある場合のみ
                    prob += pulp.lpSum([1 - w_vars[team_idx][r] for r in w_vars[team_idx]]) <= max_zero_roles_per_team

        # 任意：各チームが少なくとも1回は出場
        if require_min_participation:
            for team_idx in range(n_teams):
                prob += team_participation_vars[team_idx] >= 1

        # ----- Objective: participation and role balance (same as before) -----
        # Minimize participation max-min + role max-min (weighted)
        max_participation = pulp.LpVariable("max_participation", lowBound=0, cat='Integer')
        min_participation = pulp.LpVariable("min_participation", lowBound=0, cat='Integer')
        for team_idx in range(n_teams):
            prob += max_participation >= team_participation_vars[team_idx]
            prob += min_participation <= team_participation_vars[team_idx]

        role_balance_vars = {}
        for role in self.roles:
            if self.role_num_map.get(role, 0) > 0:
                max_role_var = pulp.LpVariable(f"max_role_{role}", lowBound=0, cat='Integer')
                min_role_var = pulp.LpVariable(f"min_role_{role}", lowBound=0, cat='Integer')
                role_balance_vars[role] = (max_role_var, min_role_var)
                for team_idx in range(n_teams):
                    prob += max_role_var >= team_role_vars[team_idx][role]
                    prob += min_role_var <= team_role_vars[team_idx][role]

        objective = (max_participation - min_participation) * balance_weight
        for role, (max_var, min_var) in role_balance_vars.items():
            weight = self.role_num_map[role] if self.role_num_map[role] > 0 else 1
            objective += (max_var - min_var) * weight * balance_weight

        prob += objective

        print(f"Solving optimization for {target_matches} matches...")
        prob.solve(pulp.PULP_CBC_CMD(msg=0))  # CBC solver silently

        status = pulp.LpStatus[prob.status]
        selected_matches = []
        if prob.status == pulp.LpStatusOptimal:
            for i in range(n_matches):
                if pulp.value(match_vars[i]) == 1:
                    selected_matches.append(i)

        # Prepare results
        team_participation = {}
        team_role_counts = {}
        for team_idx in range(n_teams):
            team_name = self.idx_team_map[str(team_idx)]
            if prob.status == pulp.LpStatusOptimal:
                team_participation[team_name] = int(pulp.value(team_participation_vars[team_idx]))
                team_role_counts[team_name] = {}
                for role in self.roles:
                    team_role_counts[team_name][role] = int(pulp.value(team_role_vars[team_idx][role]))
            else:
                team_participation[team_name] = 0
                team_role_counts[team_name] = {role: 0 for role in self.roles}

        balance_score = float(pulp.value(prob.objective)) if prob.status == pulp.LpStatusOptimal else float('inf')

        return OptimizationResult(
            selected_matches=selected_matches,
            team_participation=team_participation,
            team_role_counts=team_role_counts,
            total_matches=len(selected_matches),
            balance_score=balance_score,
            optimization_status=status
        )

    def display_results(self, result: OptimizationResult):
        """Display optimization results"""
        print(f"\n=== Optimization Results ===")
        print(f"Status: {result.optimization_status}")
        print(f"Selected matches: {result.total_matches}")
        print(f"Balance score: {result.balance_score:.2f}")

        print(f"\n=== Team Participation ===")
        for team, count in sorted(result.team_participation.items()):
            print(f"{team}: {count} matches")

        # Participation stats
        participations = list(result.team_participation.values())
        if participations:
            print(f"\nParticipation Statistics:")
            print(f"  Mean: {np.mean(participations):.2f}")
            print(f"  Std Dev: {np.std(participations):.2f}")
            print(f"  Min: {min(participations)}, Max: {max(participations)}")

        print(f"\n=== Role Distribution by Team ===")
        df_data = []
        for team in sorted(result.team_role_counts.keys()):
            row = {'Team': team}
            row.update(result.team_role_counts[team])
            row['Total_Participation'] = result.team_participation[team]
            df_data.append(row)

        df = pd.DataFrame(df_data)
        print(df.to_string(index=False))

        print(f"\n=== Role Balance Statistics ===")
        for role in self.roles:
            if self.role_num_map.get(role, 0) > 0:
                role_counts = [result.team_role_counts[team][role] for team in self.teams]
                print(f"{role}:")
                print(f"  Mean: {np.mean(role_counts):.2f}")
                print(f"  Std Dev: {np.std(role_counts):.2f}")
                print(f"  Min: {min(role_counts)}, Max: {max(role_counts)}")

    def save_results(self, result: OptimizationResult, output_path: str):
        """Save optimization results to JSON file"""
        selected_matches = [int(x) for x in result.selected_matches]
        team_participation = {k: int(v) for k, v in result.team_participation.items()}
        team_role_counts = {team: {role: int(count) for role, count in roles.items()}
                            for team, roles in result.team_role_counts.items()}

        output_data = {
            'optimization_status': result.optimization_status,
            'total_matches_selected': int(result.total_matches),
            'balance_score': float(result.balance_score),
            'selected_match_indices': selected_matches,
            'team_participation': team_participation,
            'team_role_counts': team_role_counts,
            'original_data': {
                'idx_team_map': self.idx_team_map,
                'role_num_map': self.role_num_map,
                'total_available_matches': len(self.pattern_of_matches)
            }
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {output_path}")

    def copy_selected_files(self, result: OptimizationResult):
        """Copy selected game files to selected_files directory"""
        if not self.dataset_name:
            print("Warning: Dataset name not available")
            return

        # Use absolute path from script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        source_dir = os.path.join(script_dir, "..", "data", "raw", self.dataset_name)
        dest_dir = os.path.join(script_dir, "..", "data", "selected_files", self.dataset_name)

        if not os.path.exists(source_dir):
            print(f"Warning: Source directory not found: {source_dir}")
            return

        os.makedirs(dest_dir, exist_ok=True)

        copied_count = 0
        for match_idx in result.selected_matches:
            game_name = f"game{match_idx + 1}"  # game indices start from 1
            source_file = os.path.join(source_dir, game_name)
            dest_file = os.path.join(dest_dir, game_name)

            if os.path.exists(source_file):
                shutil.copy2(source_file, dest_file)
                copied_count += 1
            else:
                print(f"Warning: Game file not found: {source_file}")

        print(f"\nCopied {copied_count} game files to: {dest_dir}")

    def save_table(self, result: OptimizationResult):
        """Save optimization results as a table in the table directory"""
        if not self.dataset_name:
            print("Warning: Dataset name not available")
            return

        # Use absolute path from script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        table_dir = os.path.join(script_dir, "..", "table", self.dataset_name)
        os.makedirs(table_dir, exist_ok=True)

        # Role distribution table
        df_data = []
        for team in sorted(result.team_role_counts.keys()):
            row = {'Team': team}
            row.update(result.team_role_counts[team])
            row['Total_Participation'] = result.team_participation[team]
            df_data.append(row)

        df = pd.DataFrame(df_data)

        csv_path = os.path.join(table_dir, f"role_distribution_{self.dataset_name}.csv")
        df.to_csv(csv_path, index=False)
        print(f"Role distribution table saved to: {csv_path}")

        try:
            excel_path = os.path.join(table_dir, f"role_distribution_{self.dataset_name}.xlsx")
            df.to_excel(excel_path, index=False)
            print(f"Role distribution table saved to: {excel_path}")
        except ImportError:
            pass

        # Summary table
        participations = list(result.team_participation.values())
        summary_data = {
            'Metric': [
                'Total Matches Selected',
                'Balance Score',
                'Optimization Status',
                'Mean Team Participation',
                'Std Dev Team Participation',
                'Min Team Participation',
                'Max Team Participation',
            ],
            'Value': [
                result.total_matches,
                f"{result.balance_score:.2f}",
                result.optimization_status,
                f"{np.mean(participations):.2f}" if participations else "0.00",
                f"{np.std(participations):.2f}" if participations else "0.00",
                min(participations) if participations else 0,
                max(participations) if participations else 0,
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_csv_path = os.path.join(table_dir, f"optimization_summary_{self.dataset_name}.csv")
        summary_df.to_csv(summary_csv_path, index=False)
        print(f"Optimization summary table saved to: {summary_csv_path}")

        # Selected matches list
        matches_data = {
            'Selected_Match_Index': result.selected_matches,
            'Game_File': [f"game{idx + 1}" for idx in result.selected_matches]
        }
        matches_df = pd.DataFrame(matches_data)
        matches_csv_path = os.path.join(table_dir, f"selected_matches_{self.dataset_name}.csv")
        matches_df.to_csv(matches_csv_path, index=False)
        print(f"Selected matches list saved to: {matches_csv_path}")

def main():
    print("=== Match Selection Optimizer (ILP only) ===\n")

    # Pattern files under ../data/pattern_of_matches/*/pattern_of_matches.json
    # Use absolute path from script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pattern_base_dir = os.path.join(script_dir, "..", "data", "pattern_of_matches")
    if not os.path.exists(pattern_base_dir):
        print(f"Pattern directory not found: {pattern_base_dir}")
        return

    pattern_files = []
    pattern_paths = []
    for item in os.listdir(pattern_base_dir):
        item_path = os.path.join(pattern_base_dir, item)
        if os.path.isdir(item_path):
            pattern_file = os.path.join(item_path, "pattern_of_matches.json")
            if os.path.exists(pattern_file):
                pattern_files.append(f"{item}/pattern_of_matches.json")
                pattern_paths.append(pattern_file)

    if not pattern_files:
        print(f"No pattern files found in {pattern_base_dir}")
        print("Expected structure: data/pattern_of_matches/*/pattern_of_matches.json")
        return

    print("Available pattern files:")
    for i, filename in enumerate(pattern_files, 1):
        print(f"  {i}. {filename}")

    # Select file
    try:
        choice = input(f"\nSelect pattern file (1-{len(pattern_files)}): ").strip()
        choice = int(choice)
        if not (1 <= choice <= len(pattern_files)):
            print("Invalid choice.")
            return
    except (ValueError, EOFError):
        print("Please enter a valid number")
        return

    selected_file = pattern_files[choice - 1]
    pattern_file_path = pattern_paths[choice - 1]
    print(f"\nSelected file: {selected_file}")

    # Parameters
    try:
        t_in = input("\nEnter target number of matches (or press Enter for default): ").strip()
        target_matches = int(t_in) if t_in else None

        z_in = input("Max zero-count roles per team (0=forbid, 1=allow one, 2=allow two; Enter for 0): ").strip()
        max_zero_roles_per_team = int(z_in) if z_in else 0

        seen_flag = input("Count only roles seen in data for each team? [Y/n] (Enter=Y): ").strip().lower()
        count_only_seen_roles = (seen_flag != 'n')

        min_part_flag = input("Require each team to appear at least once? [Y/n] (Enter=Y): ").strip().lower()
        require_min_participation = (min_part_flag != 'n')

    except (ValueError, EOFError):
        print("Using default parameters")
        target_matches = None
        max_zero_roles_per_team = 0
        count_only_seen_roles = True
        require_min_participation = True

    # Optimize (ILP only)
    optimizer = MatchSelectionOptimizer(pattern_file_path)
    print("\nRunning Integer Linear Programming optimization...")
    result = optimizer.solve_ilp_optimization(
        target_matches=target_matches,
        balance_weight=1.0,
        max_zero_roles_per_team=max_zero_roles_per_team,
        count_only_seen_roles=count_only_seen_roles,
        require_min_participation=require_min_participation
    )

    # Display & save
    optimizer.display_results(result)

    if result.total_matches > 0:
        optimizer.copy_selected_files(result)
        optimizer.save_table(result)

if __name__ == "__main__":
    main()

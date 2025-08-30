#!/usr/bin/env python3
import os
import re
import json
from collections import defaultdict
from typing import Dict, List, Set

class PatternOfMatchesGenerator:
    def __init__(self):
        self.team_to_index = {}
        self.index_to_team = {}
        self.pattern_of_matches = []
        self.role_num_map = {}
        self.target_roles = {'BODYGUARD', 'MEDIUM', 'POSSESSED', 'SEER', 'VILLAGER', 'WEREWOLF'}
        
    def normalize_team_name(self, team_name: str) -> str:
        """Normalize team name by removing suffix patterns like -A1, -B1, etc."""
        # Remove patterns like -A1, -B1, -C5 (dash followed by letter and number)
        normalized = re.sub(r'-[A-Za-z]\d+$', '', team_name)
        return normalized
    
    def setup_role_num_map(self, player_count: int):
        """Setup role_num_map based on player count"""
        if player_count == 5:
            self.role_num_map = {
                "BODYGUARD": 0,
                "MEDIUM": 0,
                "POSSESSED": 1,
                "SEER": 1,
                "VILLAGER": 2,
                "WEREWOLF": 1
            }
        elif player_count == 13:
            self.role_num_map = {
                "BODYGUARD": 1,
                "MEDIUM": 1,
                "POSSESSED": 1,
                "SEER": 1,
                "VILLAGER": 6,
                "WEREWOLF": 3
            }
        else:
            raise ValueError(f"Unsupported player count: {player_count}. Must be 5 or 13.")
    
    def parse_game_file(self, filepath: str, max_lines: int) -> Dict[str, List[int]]:
        """Parse a single game file and extract role assignments for specified number of lines"""
        role_assignments = defaultdict(list)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Process only the first max_lines
        processed_lines = 0
        for line in lines:
            if processed_lines >= max_lines:
                break
                
            line = line.strip()
            if not line:
                continue
                
            try:
                parts = line.split(',')
                if len(parts) >= 7 and parts[1] == 'status':
                    # Format: day,status,player_id,role,status,team,name
                    role = parts[3]
                    team = parts[5]
                    
                    # Only process target roles
                    if role in self.target_roles:
                        normalized_team = self.normalize_team_name(team)
                        
                        # Add team to mapping if not exists
                        if normalized_team not in self.team_to_index:
                            team_idx = len(self.team_to_index)
                            self.team_to_index[normalized_team] = team_idx
                            self.index_to_team[str(team_idx)] = normalized_team
                        
                        team_idx = self.team_to_index[normalized_team]
                        
                        # Add to role assignments if not already added
                        if team_idx not in role_assignments[role]:
                            role_assignments[role].append(team_idx)
                
                processed_lines += 1
                
            except (IndexError, ValueError) as e:
                continue
        
        # Sort the team indices for each role to ensure consistent ordering
        for role in role_assignments:
            role_assignments[role].sort()
        
        return dict(role_assignments)
    
    def process_directory(self, directory_path: str, max_lines: int):
        """Process all game files in a directory"""
        if not os.path.exists(directory_path):
            print(f"Directory not found: {directory_path}")
            return
        
        # Get all game files
        game_files = [f for f in os.listdir(directory_path) 
                     if f.startswith('game') and os.path.isfile(os.path.join(directory_path, f))]
        
        if not game_files:
            print(f"No game files found in {directory_path}")
            return
        
        # Sort game files numerically
        game_files.sort(key=lambda x: int(re.search(r'game(\d+)', x).group(1)) if re.search(r'game(\d+)', x) else 0)
        
        print(f"Processing {len(game_files)} game files with first {max_lines} lines each...")
        
        # Process each game file
        for game_file in game_files:
            filepath = os.path.join(directory_path, game_file)
            print(f"Processing {game_file}...")
            
            role_assignments = self.parse_game_file(filepath, max_lines)
            
            # Create pattern entry for this game
            pattern_entry = {}
            for role in self.target_roles:
                pattern_entry[role] = role_assignments.get(role, [])
            
            self.pattern_of_matches.append(pattern_entry)
    
    def generate_output(self) -> Dict:
        """Generate the final output structure"""
        return {
            "idx_team_map": self.index_to_team,
            "role_num_map": self.role_num_map,
            "pattern_of_matches": self.pattern_of_matches
        }
    
    def save_to_file(self, output_path: str, data: Dict):
        """Save the pattern data to a JSON file"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        print(f"Pattern of matches saved to: {output_path}")

def main():
    print("=== Pattern of Matches Generator ===\n")
    
    # Get user input for player count
    while True:
        try:
            player_count = input("Enter player count (5 or 13): ").strip()
            if player_count in ['5', '13']:
                player_count = int(player_count)
                break
            else:
                print("Please enter either 5 or 13")
        except (ValueError, EOFError):
            print("Please enter a valid number (5 or 13)")
            return
    
    # List available directories
    base_dir = "../data/raw"
    if not os.path.exists(base_dir):
        print(f"Base directory not found: {base_dir}")
        return
    
    subdirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    
    if not subdirs:
        print(f"No subdirectories found in {base_dir}")
        return
    
    # Display available directories
    print("Available data directories:")
    for i, subdir in enumerate(subdirs, 1):
        print(f"  {i}. {subdir}")
    
    # Let user select directory
    while True:
        try:
            choice = input(f"\nSelect directory (1-{len(subdirs)}): ").strip()
            if not choice:
                print("Please enter a number")
                continue
            choice = int(choice)
            if 1 <= choice <= len(subdirs):
                selected_dir = subdirs[choice - 1]
                break
            else:
                print(f"Please enter a number between 1 and {len(subdirs)}")
        except (ValueError, EOFError):
            print("Please enter a valid number")
            return
    
    data_path = os.path.join(base_dir, selected_dir)
    print(f"\nSelected directory: {data_path}")
    print(f"Processing first {player_count} lines from each game file...\n")
    
    # Initialize generator
    generator = PatternOfMatchesGenerator()
    generator.setup_role_num_map(player_count)
    
    # Process directory
    generator.process_directory(data_path, player_count)
    
    if not generator.pattern_of_matches:
        print("No pattern data generated. Please check the game files.")
        return
    
    # Generate output
    output_data = generator.generate_output()
    
    # Show summary
    print(f"\n=== Summary ===")
    print(f"Total games processed: {len(generator.pattern_of_matches)}")
    print(f"Total teams found: {len(generator.team_to_index)}")
    print(f"Teams: {', '.join(generator.index_to_team.values())}")
    
    # Save to file
    output_dir = os.path.join("..", "data", "pattern_of_matches", selected_dir)
    os.makedirs(output_dir, exist_ok=True)
    output_filename = "pattern_of_matches.json"  # 好みで名前はそのままでもOK
    output_path = os.path.join(output_dir, output_filename)
    generator.save_to_file(output_path, output_data)
    
    # Display sample output
    print(f"\n=== Sample Output ===")
    sample_data = {
        "idx_team_map": output_data["idx_team_map"],
        "role_num_map": output_data["role_num_map"],
        "pattern_of_matches": output_data["pattern_of_matches"][:3] if len(output_data["pattern_of_matches"]) >= 3 else output_data["pattern_of_matches"]
    }
    print(json.dumps(sample_data, indent=2))
    
    if len(output_data["pattern_of_matches"]) > 3:
        print(f"... and {len(output_data['pattern_of_matches']) - 3} more matches")

if __name__ == "__main__":
    main()
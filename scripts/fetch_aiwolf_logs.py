#!/usr/bin/env python3
import os
import csv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import io
import re

def get_existing_game_max(output_dir):
    """Get the maximum game number from existing files in specific directory"""
    if not os.path.exists(output_dir):
        return 0
    
    max_num = 0
    for filename in os.listdir(output_dir):
        match = re.match(r'game(\d+)$', filename)
        if match:
            num = int(match.group(1))
            max_num = max(max_num, num)
    return max_num

def decode_content(content_bytes):
    """Try to decode content with fallback encodings"""
    encodings = ['utf-8-sig', 'utf-8', 'cp932', 'latin-1']
    
    for encoding in encodings:
        try:
            return content_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    
    # If all fail, use latin-1 with errors='replace'
    return content_bytes.decode('latin-1', errors='replace')

def get_last_non_empty_line(content):
    """Get the last non-empty line from content"""
    lines = content.strip().split('\n')
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return ""

def check_log_condition(content):
    """Check if log meets the criteria based on last line"""
    last_line = get_last_non_empty_line(content)
    if not last_line:
        return False
    
    try:
        reader = csv.reader(io.StringIO(last_line))
        row = next(reader)
        
        # Must have at least 4 columns
        if len(row) < 4:
            return False
        
        # Check conditions: row[0] == "result" and row[3] in {"WEREWOLF", "VILLAGER"}
        return row[1] == "result" and row[4] in {"WEREWOLF", "VILLAGER"}
    except (csv.Error, StopIteration, IndexError):
        return False

def main():
    print("=== AIWolf Log Fetcher ===\n")
    
    # Get URL from user input
    base_url = input("Enter the log directory URL: ").strip()
    if not base_url:
        print("URL is required. Exiting.")
        return 1
    
    # Ensure URL ends with /
    if not base_url.endswith('/'):
        base_url += '/'
    
    # Extract directory name from URL for output path
    url_parts = base_url.rstrip('/').split('/')
    # Try to find a meaningful directory name from the URL
    dir_name = None
    for part in reversed(url_parts):
        if part and part not in ['log', 'logs', 'http:', 'https:', '']:
            dir_name = part.lower()
            break
    
    if not dir_name:
        dir_name = input("Enter a name for this dataset: ").strip().lower()
        if not dir_name:
            print("Dataset name is required. Exiting.")
            return 1
    
    # Create output directory
    output_dir = f"../data/raw/{dir_name}"
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nOutput directory: {output_dir}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Get starting game number for this directory
    start_game_num = get_existing_game_max(output_dir) + 1
    current_game_num = start_game_num
    
    try:
        print(f"Fetching directory page: {base_url}")
        response = requests.get(base_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all .log links
        log_links = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.endswith('.log'):
                # Skip parent directory links
                if href.startswith('../') or 'Parent Directory' in link.get_text():
                    continue
                full_url = urljoin(base_url, href)
                log_links.add(full_url)
        
        log_links = list(log_links)  # Convert to list for ordering
        print(f"Found {len(log_links)} .log files")
        
        saved_files = []
        processed_count = 0
        
        for url in log_links:
            try:
                print(f"Processing: {url}")
                log_response = requests.get(url, headers=headers, timeout=15)
                log_response.raise_for_status()
                
                # Decode content
                content = decode_content(log_response.content)
                
                # Check condition
                if check_log_condition(content):
                    # Save the file
                    output_path = os.path.join(output_dir, f"game{current_game_num}")
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    saved_files.append(f"game{current_game_num}")
                    current_game_num += 1
                    print(f"  -> Saved as game{current_game_num - 1}")
                else:
                    print(f"  -> Skipped (conditions not met)")
                
                processed_count += 1
                
            except Exception as e:
                print(f"  -> Error processing {url}: {e}")
                continue
        
        print(f"\n=== Summary ===")
        print(f"Total .log links found: {len(log_links)}")
        print(f"Successfully processed: {processed_count}")
        print(f"Files saved: {len(saved_files)}")
        
        if saved_files:
            print(f"Saved files: {', '.join(saved_files)}")
        else:
            print("No files met the criteria for saving")
            
    except Exception as e:
        print(f"Error fetching directory page: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
#!/usr/bin/env python3
"""
Ultimate Python Package Manager (Pipman-CLI)
Version 1.0.1 - Cross-Platform Edition
Compatible with Windows, macOS, and Linux
Author: Copyright (c) 2026 Irfan Haider
GitHub: https://github.com/Irfanh-dev/Pipman-CLI
"""

import subprocess
import json
import requests
import sys
import concurrent.futures
import threading
import time
import select
import re
import os
import platform
import argparse
from difflib import get_close_matches

# Store outdated packages globally
outdated_packages_global = []
# tool version; changing this updates banner, user-agent, etc.
__version__ = "1.0.1"
# global indentation used for nicer layout
INDENT = "  "

class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    RESET = '\033[0m'

class PackageScanner:
    """Manages package scanning with interrupt capability."""
    def __init__(self):
        self.scanning = False
        self.stop_requested = False
        self.results = {}
        self.lock = threading.Lock()
        self.scanned_count = 0
        self.total_packages = 0

class LoadingAnimation:
    """Display loading animation with moon phases."""
    def __init__(self, print_lock=None):
        self.moon_phases = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
        self.spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.current = 0
        self.running = False
        self.thread = None
        self.print_lock = print_lock or threading.Lock()
        self.message = ""
    
    def _animate(self):
        """Internal animation loop."""
        while self.running:
            moon = self.moon_phases[self.current % len(self.moon_phases)]
            spinner = self.spinner[self.current % len(self.spinner)]
            with self.print_lock:
                sys.stdout.write(f"\r{Colors.MAGENTA}{spinner} {self.message} {moon} {Colors.RESET}")
                sys.stdout.flush()
            self.current += 1
            time.sleep(0.1)
    
    def start(self, message="Loading"):
        """Start loading animation."""
        self.message = message
        self.running = True
        self.thread = threading.Thread(target=self._animate)
        self.thread.daemon = True
        self.thread.start()
    
    def stop(self, message=""):
        """Stop loading animation."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        with self.print_lock:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()
            if message:
                print(f"{message}")

def check_pip_availability():
    """Check if pip is available in the system."""
    try:
        # Try to run pip --version
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False

def check_and_install_dependencies(verbose=False):
    """Check for required dependencies and install if missing."""
    required_packages = {
        'requests': 'requests'
    }
    
    missing_packages = []
    
    # Check each required package
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)
    
    if not missing_packages:
        return True
    
    # If packages are missing, try to install them
    if verbose:
        print(f"\n{INDENT}{Colors.YELLOW}Missing dependencies detected:{Colors.RESET}")
        for pkg in missing_packages:
            print(f"{INDENT}{Colors.RED}✘ {pkg}{Colors.RESET}")
        print(f"\n{INDENT}{Colors.BLUE}Attempting automatic installation...{Colors.RESET}")
    
    loader = LoadingAnimation()
    
    for package in missing_packages:
        if verbose:
            loader.start(f"Installing {package}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                if verbose:
                    loader.stop(f"{INDENT}{Colors.GREEN}✔ {package} installed successfully{Colors.RESET}")
            else:
                if verbose:
                    loader.stop()
                print(f"{INDENT}{Colors.RED}✘ Failed to install {package}{Colors.RESET}")
                if result.stderr:
                    error_msg = result.stderr.split('\n')[0][:100]
                    print(f"{INDENT}{Colors.YELLOW}Error: {error_msg}{Colors.RESET}")
                return False
        except subprocess.TimeoutExpired:
            if verbose:
                loader.stop()
            print(f"{INDENT}{Colors.RED}✘ Installation timeout for {package}{Colors.RESET}")
            return False
        except Exception as e:
            if verbose:
                loader.stop()
            print(f"{INDENT}{Colors.RED}✘ Error installing {package}: {str(e)}{Colors.RESET}")
            return False
    
    if verbose:
        print(f"\n{INDENT}{Colors.GREEN}✔ All dependencies installed successfully!{Colors.RESET}")
    return True

def get_installed_packages():
    """Return dict of installed packages with current versions."""
    try:
        # Use sys.executable to ensure we use the correct Python interpreter
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"{INDENT}{Colors.RED}Error running pip: {result.stderr[:100]}{Colors.RESET}")
            return {}
        
        packages = json.loads(result.stdout)
        return {pkg["name"]: pkg["version"] for pkg in packages}
    except json.JSONDecodeError as e:
        print(f"{INDENT}{Colors.RED}Failed to parse pip output: {e}{Colors.RESET}")
        return {}
    except Exception as e:
        print(f"{INDENT}{Colors.RED}Error getting installed packages: {e}{Colors.RESET}")
        return {}

def normalize_package_name(name):
    """Normalize package name for fuzzy matching."""
    # Remove common separators and convert to lowercase
    name = name.lower()
    for sep in ['-', '_', '.', ' ', '=', '+']:
        name = name.replace(sep, '')
    return name

def find_similar_packages(all_packages, search_term, max_results=15):
    """Find packages similar to search term using intelligent matching."""
    if not all_packages:
        return []
    
    search_lower = search_term.lower()
    search_normalized = normalize_package_name(search_term)
    
    # Score each package based on match quality
    scored_packages = []
    
    for pkg in all_packages:
        pkg_lower = pkg.lower()
        pkg_normalized = normalize_package_name(pkg)
        score = 0
        
        # 1. Exact match (highest priority)
        if pkg_lower == search_lower:
            score = 1000
        
        # 2. Package name starts with search term
        elif pkg_lower.startswith(search_lower):
            score = 900
        
        # 3. Package name ends with search term
        elif pkg_lower.endswith(search_lower):
            score = 800
        
        # 4. Package contains search term as whole word
        words = re.split(r'[-_.]', pkg_lower)
        if search_lower in words:
            score = 700
        
        # 5. Package contains search term (not necessarily whole word)
        elif search_lower in pkg_lower:
            score = 500
        
        # 6. Normalized package contains normalized search term
        elif search_normalized and search_normalized in pkg_normalized:
            score = 300
        
        if score > 0:
            scored_packages.append((score, pkg))
    
    # Sort by score (descending)
    scored_packages.sort(reverse=True, key=lambda x: x[0])
    
    # Get top matches
    top_matches = [pkg for score, pkg in scored_packages[:max_results]]
    
    # If we don't have enough matches and search term is reasonable length,
    # add some fuzzy matches as last resort
    if len(top_matches) < 3 and len(search_lower) > 2:
        remaining = [p for p in all_packages if p not in top_matches]
        if remaining:
            fuzzy = get_close_matches(
                search_lower,
                remaining,
                n=2,
                cutoff=0.7
            )
            for pkg in fuzzy:
                if pkg not in top_matches:
                    top_matches.append(pkg)
    
    return top_matches[:max_results]

def get_package_info_simple(package_name):
    """Get only basic package info - faster than full metadata."""
    try:
        # Add timeout and better error handling
        response = requests.get(
            f"https://pypi.org/pypi/{package_name}/json",
            timeout=5,
            headers={'User-Agent': f'pipman-cli/{__version__}'}
        )
        
        if response.status_code == 200:
            info = response.json()
            latest_version = info["info"]["version"]
            
            # Get approximate size from first available release file
            releases = info["releases"].get(latest_version, [])
            size_bytes = 0
            
            for release in releases:
                if release.get("size"):
                    size_bytes = release.get("size")
                    break
            
            size_mb = round(size_bytes / (1024 * 1024), 1) if size_bytes > 0 else 0
            
            return {
                "latest": latest_version,
                "size": size_mb,
                "success": True,
                "summary": info["info"].get("summary", "")
            }
        elif response.status_code == 404:
            return {"latest": None, "size": 0, "success": False, "error": "Package not found on PyPI"}
    except requests.exceptions.Timeout:
        return {"latest": None, "size": 0, "success": False, "error": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"latest": None, "size": 0, "success": False, "error": "Network connection error"}
    except requests.RequestException as e:
        return {"latest": None, "size": 0, "success": False, "error": str(e)}
    
    return {"latest": None, "size": 0, "success": False, "error": "Unknown error"}

def scan_package_batch(package_names, scanner):
    """Scan a batch of packages with progress reporting."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_package = {
            executor.submit(get_package_info_simple, name): name 
            for name in package_names
        }
        
        for future in concurrent.futures.as_completed(future_to_package):
            if scanner.stop_requested:
                break
                
            package_name = future_to_package[future]
            try:
                result = future.result(timeout=5)
                with scanner.lock:
                    scanner.results[package_name] = result
                    scanner.scanned_count += 1
            except Exception as e:
                with scanner.lock:
                    scanner.results[package_name] = {
                        "latest": None, 
                        "size": 0, 
                        "success": False, 
                        "error": str(e)
                    }
                    scanner.scanned_count += 1

def show_packages_with_progress(installed, scanner):
    """Display packages with real-time progress and clear after scan."""
    print(f"\n{Colors.BOLD}{'Package':<30}{'Current':<15}{'Latest':<15}{'Size':<8}{'Status':<10}{Colors.RESET}")
    print(f"{Colors.CYAN}{'-'*88}{Colors.RESET}")
    
    # Store the lines that will be printed during scanning
    scan_output_lines = []
    scan_output_lines.append(f"\n{Colors.BOLD}{'Package':<30}{'Current':<15}{'Latest':<15}{'Size':<8}{'Status':<10}{Colors.RESET}")
    scan_output_lines.append(f"{Colors.CYAN}{'-'*88}{Colors.RESET}")
    
    # Start scanning in background thread
    scanner.scanning = True
    scanner.total_packages = len(installed)
    
    # Start scanning thread
    scan_thread = threading.Thread(
        target=scan_package_batch, 
        args=(list(installed.keys()), scanner)
    )
    scan_thread.daemon = True
    scan_thread.start()
    
    outdated = {}
    displayed_packages = set()
    
    # Create a shared print lock for animation and package printing
    print_lock = threading.Lock()
    
    # Start loading animation
    loader = LoadingAnimation(print_lock=print_lock)
    loader.start(f"Scanning packages [0/{scanner.total_packages}]")
    
    try:
        while scanner.scanning and not scanner.stop_requested:
            # Display newly scanned packages
            with scanner.lock:
                current_scanned = scanner.scanned_count
                # Update animation message with progress
                loader.message = f"Scanning packages [{current_scanned}/{scanner.total_packages}]"
                
                # Display newly scanned packages
                for name, current in installed.items():
                    if name in scanner.results and name not in displayed_packages:
                        result = scanner.results[name]
                        latest = result.get("latest")
                        size = result.get("size", 0)
                        # Determine color and status
                        if latest is None:
                            name_color = Colors.YELLOW
                            status = "unknown"
                        elif latest == current:
                            name_color = Colors.GREEN
                            status = "updated"
                        else:
                            name_color = Colors.RED
                            status = "outdated"
                            outdated[name] = (latest, size)
                        latest_display = latest if latest else '-'
                        size_display = f"{size:.1f}M" if size > 0 else '-'
                        status_display = status.upper()
                        
                        # Stop animation temporarily to print package line
                        loader.stop()
                        
                        line = (f"{name_color}{name:<30}{Colors.RESET}"
                              f"{Colors.WHITE}{current:<15}{Colors.RESET}"
                              f"{Colors.CYAN}{latest_display:<15}{Colors.RESET}"
                              f"{Colors.YELLOW}{size_display:<8}{Colors.RESET}"
                              f"{name_color}{status_display:<10}{Colors.RESET}")
                        print(line)
                        scan_output_lines.append(line)
                        
                        # Restart animation
                        loader.start(f"Scanning packages [{current_scanned}/{scanner.total_packages}]")
                        
                        displayed_packages.add(name)
            
            # Check for user interrupt (non-blocking, cross-platform)
            try:
                if os.name == 'nt':  # Windows
                    import msvcrt
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch.lower() == 'q':
                            loader.stop()
                            with print_lock:
                                print(f"\n{INDENT}{Colors.YELLOW}Scan interrupted by user.{Colors.RESET}")
                            scanner.stop_requested = True
                            break
                        elif ch == '\x74':  # F5 key code is 0x74
                            loader.stop()
                            with print_lock:
                                print(f"\n{INDENT}{Colors.BLUE}F5 pressed. Restarting...{Colors.RESET}")
                            restart_program()
                else:  # Unix/Linux/macOS
                    if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                        line = sys.stdin.readline().strip()
                        if line and line.lower() == 'q':
                            loader.stop()
                            with print_lock:
                                print(f"\n{INDENT}{Colors.YELLOW}Scan interrupted by user.{Colors.RESET}")
                            scanner.stop_requested = True
                            break
                        elif line == '\x74':  # F5 key code
                            loader.stop()
                            with print_lock:
                                print(f"\n{INDENT}{Colors.BLUE}F5 pressed. Restarting...{Colors.RESET}")
                            restart_program()
            except Exception:
                pass
            
            # Check if scanning is complete
            if scanner.scanned_count >= scanner.total_packages:
                scanner.scanning = False
                break
            
            # Small sleep to prevent CPU spinning
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        loader.stop()
        with print_lock:
            print(f"\n{INDENT}{Colors.YELLOW}Scan interrupted by Ctrl+C.{Colors.RESET}")
        scanner.stop_requested = True
    finally:
        # Stop loading animation
        loader.stop()
        
        # Wait for scan thread to finish
        scanner.scanning = False
        scan_thread.join(timeout=2)
        
        # Clear all scan output lines from terminal before final summary
        # (only if the scan completed without interruption)
        if not scanner.stop_requested:
            # Move up the number of lines printed + 1 for the loader line, and clear each
            for _ in range(len(scan_output_lines)):
                sys.stdout.write("\033[F\033[2K")  # Move up one line and clear it
            sys.stdout.flush()
        
        # Show interrupted results if scan was stopped early
        if scanner.stop_requested:
            print(f"\n{Colors.BOLD}INTERRUPTED SCAN RESULTS:{Colors.RESET}")
            print(f"{Colors.BOLD}{'Package':<30}{'Current':<15}{'Latest':<15}{'Size':<8}{'Status':<10}{Colors.RESET}")
            print(f"{Colors.CYAN}{'-'*88}{Colors.RESET}")
            for name in scanner.results:
                current = installed.get(name, '-')
                result = scanner.results[name]
                latest = result.get("latest")
                size = result.get("size", 0)
                if latest is None:
                    name_color = Colors.YELLOW
                    status = "unknown"
                elif latest == current:
                    name_color = Colors.GREEN
                    status = "updated"
                else:
                    name_color = Colors.RED
                    status = "outdated"
                latest_display = latest if latest else '-'
                size_display = f"{size:.1f}M" if size > 0 else '-'
                status_display = status.upper()
                print(f"{name_color}{name:<30}{Colors.RESET}"
                      f"{Colors.WHITE}{current:<15}{Colors.RESET}"
                      f"{Colors.CYAN}{latest_display:<15}{Colors.RESET}"
                      f"{Colors.YELLOW}{size_display:<8}{Colors.RESET}"
                      f"{name_color}{status_display:<10}{Colors.RESET}")
    
    return outdated

def show_packages_final(installed, outdated_info):
    """Display final package list after scanning."""
    print(f"\n{INDENT}{Colors.BOLD}FINAL RESULTS:{Colors.RESET}")
    print(f"{Colors.BOLD}{'Package':<30}{'Current':<15}{'Latest':<15}{'Size':<8}{'Status':<10}{Colors.RESET}")
    print(f"{Colors.CYAN}{'-'*88}{Colors.RESET}")
    
    outdated = {}
    
    for name, current in installed.items():
        result = outdated_info.get(name, {"latest": None, "size": 0})
        latest = result.get("latest")
        size = result.get("size", 0)
        
        if latest and latest != current:
            outdated[name] = (latest, size)
            name_color = Colors.RED
            status = "OUTDATED"
        elif latest == current:
            name_color = Colors.GREEN
            status = "UPDATED"
        else:
            name_color = Colors.YELLOW
            status = "UNKNOWN"
        
        latest_display = latest if latest else '-'
        size_display = f"{size:.1f}M" if size > 0 else '-'
        
        print(f"{name_color}{name:<30}{Colors.RESET}"
              f"{Colors.WHITE}{current:<15}{Colors.RESET}"
              f"{Colors.CYAN}{latest_display:<15}{Colors.RESET}"
              f"{Colors.YELLOW}{size_display:<8}{Colors.RESET}"
              f"{name_color}{status:<10}{Colors.RESET}")
    
    return outdated

def update_packages(packages_to_update):
    """Update packages using pip, handle pip specially."""
    if not packages_to_update:
        print(f"{INDENT}{Colors.YELLOW}No packages to update.{Colors.RESET}")
        return
    
    print(f"\n{INDENT}{Colors.BLUE}Preparing to update {len(packages_to_update)} package(s)...{Colors.RESET}")
    
    for i, name in enumerate(packages_to_update, 1):
        print(f"\n{INDENT}{Colors.BLUE}[{i}/{len(packages_to_update)}] {Colors.BOLD}{name}{Colors.RESET}")
        
        # Create loading animation for this package update
        loader = LoadingAnimation()
        loader.start(f"Updating {name}")
        
        try:
            if name.lower() == "pip":
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "pip"], 
                    capture_output=True, 
                    text=True
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", name], 
                    capture_output=True, 
                    text=True
                )
            
            loader.stop()
            
            if result.returncode == 0:
                print(f"{INDENT}{Colors.GREEN}✔ Successfully updated {name}{Colors.RESET}")
            else:
                print(f"{INDENT}{Colors.RED}✘ Failed to update {name}{Colors.RESET}")
                if result.stderr:
                    error_msg = result.stderr.split('\n')[0][:100]
                    print(f"{INDENT}{Colors.YELLOW}Error: {error_msg}...{Colors.RESET}")
        except Exception as e:
            loader.stop()
            print(f"{INDENT}{Colors.RED}✘ Error updating {name}: {str(e)[:50]}{Colors.RESET}")
    
    print(f"\n{INDENT}{Colors.GREEN}✅ Update finished!{Colors.RESET}")

def parse_selection_input(selection_str, max_number):
    """Parse user selection input like '1,3,5' or '1-5' or 'all'."""
    selection_str = selection_str.strip().lower()
    
    if selection_str == 'all':
        return list(range(1, max_number + 1))
    
    selected_numbers = set()
    parts = selection_str.split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        if '-' in part:
            range_parts = part.split('-')
            if len(range_parts) == 2:
                try:
                    start = int(range_parts[0].strip())
                    end = int(range_parts[1].strip())
                    if 1 <= start <= end <= max_number:
                        selected_numbers.update(range(start, end + 1))
                    else:
                        return None
                except ValueError:
                    return None
        else:
            try:
                num = int(part)
                if 1 <= num <= max_number:
                    selected_numbers.add(num)
                else:
                    return None
            except ValueError:
                return None
    
    return sorted(selected_numbers)

def select_packages_from_matches(matches, search_term):
    """Let user select one or multiple packages from matches."""
    if not matches:
        print(f"{Colors.RED}No packages found matching '{search_term}'.{Colors.RESET}")
        return None
    
    # if the top match is exactly the search term, select it immediately
    if matches[0].lower() == search_term.lower():
        print(f"{Colors.GREEN}Auto-selected exact match: {matches[0]}{Colors.RESET}")
        return [matches[0]]
    
    if len(matches) == 1:
        print(f"{Colors.GREEN}Found: {matches[0]}{Colors.RESET}")
        # Automatically proceed when only one match
        return [matches[0]]
    
    print(f"\n{Colors.BLUE}Found {len(matches)} packages matching '{search_term}':{Colors.RESET}")
    
    # Show matches with explanation
    for i, pkg in enumerate(matches, 1):
        pkg_lower = pkg.lower()
        if pkg_lower == search_term.lower():
            reason = "Exact match"
        elif pkg_lower.startswith(search_term.lower()):
            reason = f"Starts with '{search_term}'"
        elif pkg_lower.endswith(search_term.lower()):
            reason = f"Ends with '{search_term}'"
        elif search_term.lower() in re.split(r'[-_.]', pkg_lower):
            reason = f"Contains '{search_term}' as a word"
        elif search_term.lower() in pkg_lower:
            reason = f"Contains '{search_term}'"
        else:
            reason = "Similar match"
        
        print(f"  {Colors.CYAN}{i:>2}.{Colors.RESET} {Colors.BOLD}{pkg:<30}{Colors.RESET} ({Colors.YELLOW}{reason}{Colors.RESET})")
    
    print(f"\n{Colors.BOLD}Selection Options:{Colors.RESET}")
    print(f"  {Colors.CYAN}Single:{Colors.RESET}   Enter a single number (e.g., 1)")
    print(f"  {Colors.CYAN}Multiple:{Colors.RESET} Enter comma-separated numbers (e.g., 1,3,5)")
    print(f"  {Colors.CYAN}Range:{Colors.RESET}    Enter a range (e.g., 1-5)")
    print(f"  {Colors.CYAN}All:{Colors.RESET}      Enter 'all' to select all {len(matches)} packages")
    print(f"  {Colors.CYAN}Cancel:{Colors.RESET}   Enter '0' or 'cancel'")
    
    while True:
        try:
            choice = input(f"\n{Colors.BOLD}Select packages (1-{len(matches)}): {Colors.RESET}").strip()
            
            if choice.lower() in ['0', 'cancel', 'exit', 'quit']:
                print(f"{Colors.YELLOW}Cancelled.{Colors.RESET}")
                return None
            
            selected_numbers = parse_selection_input(choice, len(matches))
            
            if selected_numbers is None:
                print(f"{Colors.RED}Invalid selection. Please enter valid numbers between 1 and {len(matches)}.{Colors.RESET}")
                continue
            
            if not selected_numbers:
                print(f"{Colors.YELLOW}No packages selected.{Colors.RESET}")
                return None
            
            selected_packages = [matches[i-1] for i in selected_numbers]
            
            print(f"\n{Colors.BLUE}Selected {len(selected_packages)} package(s):{Colors.RESET}")
            for i, pkg in enumerate(selected_packages, 1):
                print(f"  {Colors.CYAN}{i}.{Colors.RESET} {pkg}")
            
            # Automatically proceed with the selection without asking for confirmation
            return selected_packages
                
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}Cancelled.{Colors.RESET}")
            return None
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
            return None

def print_color_legend():
    """Print legend explaining the color codes."""
    print(f"\n{Colors.BOLD}Color Legend:{Colors.RESET}")
    print(f"{Colors.GREEN}Green{Colors.RESET}   → Package is up-to-date")
    print(f"{Colors.RED}Red{Colors.RESET}     → Update available")
    print(f"{Colors.YELLOW}Yellow{Colors.RESET}  → Status unknown")
    print(f"{Colors.CYAN}Cyan{Colors.RESET}    → Latest version")
    print(f"{Colors.WHITE}White{Colors.RESET}   → Current version")
    print(f"{Colors.BLUE}Blue{Colors.RESET}    → Action/Progress")
    print(f"{Colors.MAGENTA}Magenta{Colors.RESET} → Loading animation")
    print(f"{Colors.CYAN}{'-'*40}{Colors.RESET}")

def quick_update_specific(package_name):
    """Quickly update a specific package without full scan."""
    print(f"\n{INDENT}{Colors.BLUE}Quick update for: {Colors.BOLD}{package_name}{Colors.RESET}")
    
    # Create loading animation
    loader = LoadingAnimation()
    loader.start("Checking current version")
    
    installed = get_installed_packages()
    
    loader.stop()
    
    if package_name not in installed:
        print(f"{INDENT}{Colors.RED}Package '{package_name}' is not installed.{Colors.RESET}")
        return False
    
    current_version = installed[package_name]
    print(f"{INDENT}{Colors.WHITE}Current version: {current_version}{Colors.RESET}")
    
    # Get latest version with loading animation
    loader.start("Fetching latest version")
    result = get_package_info_simple(package_name)
    loader.stop()
    
    if result["success"]:
        latest_version = result["latest"]
        size_mb = result["size"]
        
        if latest_version == current_version:
            print(f"{INDENT}{Colors.GREEN}✔ {package_name} is already up-to-date ({current_version}){Colors.RESET}")
            return True
        else:
            print(f"{INDENT}{Colors.CYAN}Latest version: {latest_version}{Colors.RESET}")
            print(f"{INDENT}{Colors.YELLOW}Download size: ~{size_mb:.1f} MB{Colors.RESET}")
            
            # Automatically perform the update without asking
            update_packages([package_name])
            return True
    else:
        print(f"{INDENT}{Colors.RED}Could not fetch information for {package_name}{Colors.RESET}")
        if result.get("error"):
            print(f"{INDENT}{Colors.YELLOW}Error: {result['error']}{Colors.RESET}")
        return False

def batch_update_packages(package_names):
    """Update multiple packages without asking for confirmation."""
    if not package_names:
        print(f"{INDENT}{Colors.YELLOW}No packages selected.{Colors.RESET}")
        return False
    
    print(f"\n{INDENT}{Colors.BLUE}Batch update for {len(package_names)} packages:{Colors.RESET}")
    for i, pkg in enumerate(package_names, 1):
        print(f"{INDENT}{Colors.CYAN}{i}.{Colors.RESET} {pkg}")
    
    # Proceed directly
    update_packages(package_names)
    return True

def smart_update_command(user_input):
    """Handle smart update command with intelligent matching."""
    search_term = user_input[7:].strip()
    
    if not search_term:
        print(f"{INDENT}{Colors.RED}Please specify a package name or pattern.{Colors.RESET}")
        return
    
    if search_term.lower() == "all":
        global outdated_packages_global
        if not outdated_packages_global:
            print(f"{INDENT}{Colors.YELLOW}To update all outdated packages, please run 'scan' first.{Colors.RESET}")
            print(f"{INDENT}{Colors.BLUE}Or use 'update <pattern>' to update all packages matching a pattern.{Colors.RESET}")
            return
        print(f"{INDENT}{Colors.BLUE}Updating all {len(outdated_packages_global)} outdated packages...{Colors.RESET}")
        batch_update_packages(outdated_packages_global)
        return
    
    # Create loading animation
    loader = LoadingAnimation()
    loader.start("Searching installed packages")
    
    installed = get_installed_packages()
    
    loader.stop()
    
    if not installed:
        print(f"{INDENT}{Colors.YELLOW}No packages installed.{Colors.RESET}")
        return
    
    # Find similar packages using intelligent matching
    matches = find_similar_packages(list(installed.keys()), search_term)
    
    if not matches:
        print(f"{INDENT}{Colors.RED}No packages found matching '{search_term}'.{Colors.RESET}")
        print(f"{INDENT}{Colors.YELLOW}Try a different search term or use 'list' to see all packages.{Colors.RESET}")
        return
    
    # Let user select packages
    selected_packages = select_packages_from_matches(matches, search_term)
    
    if selected_packages:
        if len(selected_packages) == 1:
            quick_update_specific(selected_packages[0])
        else:
            batch_update_packages(selected_packages)

def print_banner():
    """Print the application banner with left-aligned text."""
    border = '=' * 60
    banner = f"""
{Colors.CYAN}{border}{Colors.RESET}
  {Colors.BOLD}ULTIMATE PYTHON PACKAGE MANAGER (Pipman-CLI){Colors.RESET}
  {Colors.WHITE}Version {__version__} | Cross-Platform Edition{Colors.RESET}
  {Colors.YELLOW}Author: Copyright (c) 2026 Irfan Haider{Colors.RESET}
  {Colors.BLUE}GitHub: https://github.com/Irfanh-dev/Pipman-CLI{Colors.RESET}
{Colors.CYAN}{border}{Colors.RESET}
"""
    print(banner)

def print_commands():
    """Print available commands."""
    print(f"\n{INDENT}{Colors.BOLD}Smart Commands:{Colors.RESET}")
    print(f"{INDENT}{Colors.GREEN}{'scan':<22}{Colors.RESET}→ Scan all packages ")
    print(f"{INDENT}{Colors.CYAN}{'update <name/pattern>':<22}{Colors.RESET}→ Smart update with multi-select")
    print(f"{INDENT}{Colors.BLUE}{'list':<22}{Colors.RESET}→ Show installed packages only")
    print(f"{INDENT}{Colors.YELLOW}{'exit':<22}{Colors.RESET}→ Exit program")
    print(f"{INDENT}{Colors.WHITE}{'help':<22}{Colors.RESET}→ Show help")
    print(f"{INDENT}{Colors.MAGENTA}{'legend':<22}{Colors.RESET}→ Show color legend")

    print(f"\n{INDENT}{Colors.BOLD}Selection Examples:{Colors.RESET}")
    print(f"{INDENT}{Colors.CYAN}{'update pyqt':<22}{Colors.RESET}        → Shows all PyQt packages")
    print(f"{INDENT}{'Then enter:':<22}{Colors.RESET}{Colors.GREEN}{'all':<8}{Colors.RESET}→ Update all matching")
    print(f"{INDENT}{'Or enter:':<22}{Colors.RESET}{Colors.GREEN}{'1,3,5':<8}{Colors.RESET}→ Update packages 1, 3, and 5")
    print(f"{INDENT}{'Or enter:':<22}{Colors.RESET}{Colors.GREEN}{'1-4':<8}{Colors.RESET}→ Update packages 1 through 4")

def main():
    """Main function."""
    # simple CLI parsing
    parser = argparse.ArgumentParser(prog="pipman-cli", description="Ultimate Python Package Manager (Pipman-CLI)")
    parser.add_argument("--version", "-V", action="store_true", help="Show version and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run (scan, update, etc.)")
    args = parser.parse_args()

    if args.version:
        print(f"pipmancli {__version__}")
        return

    # Clear screen
    os.system('cls' if platform.system() == 'Windows' else 'clear')
    
    # Print banner
    print_banner()
    
    # Check if pip is available
    print(f"{INDENT}{Colors.BLUE}Checking system compatibility...{Colors.RESET}")
    
    loader = LoadingAnimation()
    loader.start("Checking pip availability")
    
    if not check_pip_availability():
        loader.stop(f"{INDENT}{Colors.RED}✘ pip is not available!{Colors.RESET}")
        print(f"\n{Colors.YELLOW}Please ensure pip is installed and in your PATH.{Colors.RESET}")
        print(f"{Colors.WHITE}You can install pip with: {Colors.CYAN}python -m ensurepip --upgrade{Colors.RESET}")
        return
    loader.stop(f"{INDENT}{Colors.GREEN}✓ pip is available{Colors.RESET}")
    
    # Check and install required dependencies (silently in background)
    check_and_install_dependencies(verbose=False)
    
    # Show OS info
    print(f"\n{INDENT}{Colors.WHITE}System: {Colors.CYAN}{platform.system()} {platform.release()}{Colors.RESET}")
    print(f"{INDENT}{Colors.WHITE}Python: {Colors.CYAN}{sys.version.split()[0]}{Colors.RESET}")
    
    # Print commands
    print_commands()
    
    # if a command was passed via CLI arguments, execute it and exit
    if args.command:
        user_input = " ".join(args.command).strip()
        run_command(user_input)
        return
    
    # otherwise enter interactive prompt
    while True:
        try:
            user_input = input(f"\n{Colors.BOLD}{Colors.CYAN}Pipman-CLI>{Colors.RESET} ").strip()
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}\nExiting...{Colors.RESET}")
            break
        except EOFError:
            print(f"\n{Colors.YELLOW}\nExiting...{Colors.RESET}")
            break

        if not user_input:
            continue

        if not run_command(user_input):
            break


def run_command(user_input):
    """Process a single command string; return False if the loop should exit."""
    if not user_input:
        return True
    cmd = user_input.strip().lower()

    if cmd == "exit":
        print(f"{INDENT}{Colors.YELLOW}Exiting...{Colors.RESET}")
        return False
    elif cmd == "help":
        print_commands()
    elif cmd == "legend":
        print_color_legend()
    elif cmd == "list":
        loader = LoadingAnimation()
        loader.start("Fetching installed packages")
        installed = get_installed_packages()
        loader.stop()
        
        if not installed:
            print(f"{INDENT}{Colors.YELLOW}No packages installed.{Colors.RESET}")
        else:
            print(f"\n{INDENT}{Colors.BOLD}{'Package':<30}{'Version':<20}{Colors.RESET}")
            print(f"{INDENT}{Colors.WHITE}{'-'*50}{Colors.RESET}")
            for name, version in installed.items():
                print(f"{INDENT}{Colors.WHITE}{name:<30}{version:<20}{Colors.RESET}")
            print(f"\n{INDENT}{Colors.GREEN}Total: {len(installed)} packages{Colors.RESET}")
    elif cmd.startswith("update "):
        raw = user_input[7:]
        terms = [t.strip().strip(' .;') for t in raw.split(',') if t.strip()]
        if len(terms) > 1:
            for term in terms:
                smart_update_command(f"update {term}")
        else:
            smart_update_command(user_input)
    elif cmd == "scan":
        loader = LoadingAnimation()
        loader.start("Fetching installed packages")
        installed = get_installed_packages()
        loader.stop()
        
        if not installed:
            print(f"{INDENT}{Colors.YELLOW}No packages installed.{Colors.RESET}")
        else:
            scanner = PackageScanner()
            print(f"\n{INDENT}{Colors.YELLOW}Starting scan of {len(installed)} packages...{Colors.RESET}")
            print(f"{INDENT}{Colors.BLUE}Press 'q' during scan to stop early{Colors.RESET}\n")
            try:
                outdated = show_packages_with_progress(installed, scanner)
                # Only print final/summary if not interrupted
                if not scanner.stop_requested:
                    outdated_info = scanner.results
                    outdated = show_packages_final(installed, outdated_info)
                    total = len(installed)
                    outdated_count = len(outdated)
                    scanned_count = scanner.scanned_count
                    print(f"\n{INDENT}{Colors.BOLD}Scan Summary:{Colors.RESET}")
                    print(f"{INDENT}{Colors.GREEN}✅ Up-to-date: {total - outdated_count}{Colors.RESET}")
                    print(f"{INDENT}{Colors.RED}🔄 Outdated: {outdated_count}{Colors.RESET}")
                    print(f"{INDENT}{Colors.CYAN}📦 Scanned: {scanned_count}/{total}{Colors.RESET}")
                print(f"{INDENT}{Colors.YELLOW}⚡ Scan interrupted: {'Yes' if scanner.stop_requested else 'No'}{Colors.RESET}")
                global outdated_packages_global
                if outdated:
                    print(f"\n{INDENT}{Colors.BOLD}Update Commands:{Colors.RESET}")
                    outdated_list = list(outdated.keys())
                    print(f"{INDENT}{Colors.GREEN}update all{Colors.RESET}              → Update all {len(outdated)} outdated packages")
                    print(f"{INDENT}{Colors.CYAN}update   <name/pattern>{Colors.RESET} → Smart update with multi-select")
                    if outdated_list:
                        print(f"{INDENT}Example: {Colors.BLUE}update {outdated_list[0]}{Colors.RESET}")
                    # Store outdated packages globally for update all
                    outdated_packages_global = outdated_list
                else:
                    outdated_packages_global = []
            except Exception as e:
                print(f"{INDENT}{Colors.RED}Scan error: {e}{Colors.RESET}")
    else:
        print(f"{INDENT}{Colors.RED}Unknown command. Type 'help' for available commands.{Colors.RESET}")
    return True

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}\nProgram interrupted. Exiting...{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.RED}Fatal error: {e}{Colors.RESET}")
        sys.exit(1)
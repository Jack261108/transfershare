"""
Update GitHub repository secrets from baidu_cookies.env using GitHub CLI.

Prerequisite:
  - Install GitHub CLI and login: `brew install gh && gh auth login`

Usage:
  python scripts/update_github_secrets.py --repo owner/repo --env baidu_cookies.env
  python scripts/update_github_secrets.py --repo owner/repo --min-only
  python scripts/update_github_secrets.py --repo owner/repo --full-only
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

def read_env_values(env_path: Path):
    text = env_path.read_text(encoding="utf-8")
    def extract(key: str):
        # Match lines like KEY="value"
        m = re.search(rf'^{re.escape(key)}="(.*)"\s*$', text, re.MULTILINE)
        return m.group(1) if m else ""
    return {
        "BAIDU_COOKIES": extract("BAIDU_COOKIES"),
        "BAIDU_COOKIES_FULL": extract("BAIDU_COOKIES_FULL"),
    }

def ensure_gh():
    try:
        subprocess.run(["gh", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        print("gh CLI not found. Install and login:\n  brew install gh\n  gh auth login")
        sys.exit(1)

def set_secret(repo: str, name: str, value: str):
    if not value:
        print(f"skip {name}: empty")
        return
    print(f"set {name} on {repo}")
    subprocess.run(["gh", "secret", "set", name, "-R", repo, "--body", value], check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--env", default="baidu_cookies.env", help="env file path")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--min-only", action="store_true", help="only set BAIDU_COOKIES")
    g.add_argument("--full-only", action="store_true", help="only set BAIDU_COOKIES_FULL")
    args = ap.parse_args()

    env_path = Path(args.env)
    if not env_path.exists():
        print(f"Env file not found: {env_path}")
        sys.exit(1)

    ensure_gh()
    vals = read_env_values(env_path)

    try:
        if args.min_only:
            set_secret(args.repo, "BAIDU_COOKIES", vals["BAIDU_COOKIES"])
        elif args.full_only:
            set_secret(args.repo, "BAIDU_COOKIES_FULL", vals["BAIDU_COOKIES_FULL"])
        else:
            set_secret(args.repo, "BAIDU_COOKIES", vals["BAIDU_COOKIES"])
            set_secret(args.repo, "BAIDU_COOKIES_FULL", vals["BAIDU_COOKIES_FULL"])
        print("Done.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to set secrets via gh: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
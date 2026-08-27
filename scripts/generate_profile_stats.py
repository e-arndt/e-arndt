from __future__ import annotations

import datetime as dt
import html
import json
import os
import urllib.request
from collections import Counter
from pathlib import Path

USERNAME = os.environ.get("GITHUB_USERNAME", "e-arndt")
TOKEN = os.environ["GITHUB_TOKEN"]
API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "github-profile-stats-generator",
}

def request_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def graphql(query: str, variables: dict):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = dict(HEADERS)
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(GRAPHQL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]

def paginate(url: str, max_pages: int = 20):
    items = []
    separator = "&" if "?" in url else "?"
    for page in range(1, max_pages + 1):
        batch = request_json(f"{url}{separator}per_page=100&page={page}")
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
    return items

def get_contribution_stats():
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime(now.year, 1, 1, tzinfo=dt.timezone.utc)
    query = '''
    query($login:String!, $from:DateTime!, $to:DateTime!) {
      user(login:$login) {
        contributionsCollection(from:$from, to:$to) {
          contributionCalendar { totalContributions }
          totalCommitContributions
          totalPullRequestContributions
        }
      }
    }
    '''
    data = graphql(query, {
        "login": USERNAME,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
    })
    c = data["user"]["contributionsCollection"]
    return (
        c["contributionCalendar"]["totalContributions"],
        c["totalCommitContributions"],
        c["totalPullRequestContributions"],
    )

def get_repos():
    repos = paginate(f"{API}/users/{USERNAME}/repos?type=owner&sort=updated")
    return [r for r in repos if not r.get("fork") and not r.get("archived")]

def get_release_data(repos):
    total = 0
    latest = None
    for repo in repos:
        releases = paginate(f"{API}/repos/{USERNAME}/{repo['name']}/releases", max_pages=5)
        total += len(releases)
        for release in releases:
            published = release.get("published_at")
            if published and (latest is None or published > latest["published_at"]):
                latest = {
                    "repo": repo["name"],
                    "name": release.get("name") or release.get("tag_name") or "Release",
                    "published_at": published,
                }
    return total, latest

def get_languages(repos):
    totals = Counter()
    for repo in repos:
        if repo.get("size", 0) == 0:
            continue
        try:
            totals.update(request_json(f"{API}/repos/{USERNAME}/{repo['name']}/languages"))
        except Exception:
            continue
    return totals

LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "PowerShell": "#5391fe",
    "Python": "#3572A5", "Rust": "#dea584", "HTML": "#e34c26", "CSS": "#563d7c",
    "Shell": "#89e051", "Batchfile": "#C1F12E", "Dockerfile": "#384d54",
    "C#": "#178600", "C++": "#f34b7d", "C": "#555555", "Java": "#b07219",
    "PHP": "#4F5D95", "Go": "#00ADD8",
}

def esc(value):
    return html.escape(str(value), quote=True)

def short(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

def render_svg(repo_count, contributions, commits, prs, releases, latest, languages):
    total_bytes = sum(languages.values()) or 1
    top = languages.most_common(7)
    rows = []
    y = 356
    for lang, count in top:
        pct = count / total_bytes
        color = LANG_COLORS.get(lang, "#8b949e")
        bar_width = max(2, int(530 * pct))
        rows.append(
            f'<circle cx="50" cy="{y-5}" r="6" fill="{color}"/>'
            f'<text x="68" y="{y}" class="lang">{esc(lang)}</text>'
            f'<rect x="215" y="{y-15}" width="530" height="12" rx="6" fill="#21262d"/>'
            f'<rect x="215" y="{y-15}" width="{bar_width}" height="12" rx="6" fill="{color}"/>'
            f'<text x="790" y="{y}" class="pct">{pct*100:.1f}%</text>'
        )
        y += 27

    latest_name = "No published release found"
    latest_date = ""
    if latest:
        latest_name = f"{latest['repo']} · {latest['name']}"
        parsed = dt.datetime.fromisoformat(latest["published_at"].replace("Z", "+00:00"))
        latest_date = parsed.strftime("%b %Y")

    metrics = [
        ("CONTRIBUTIONS THIS YEAR", contributions, "#58a6ff"),
        ("PUBLIC REPOS", repo_count, "#3fb950"),
        ("PULL REQUESTS", prs, "#bc8cff"),
        ("PUBLISHED RELEASES", releases, "#f0883e"),
    ]
    positions = [35, 245, 455, 665]
    metric_svg = []
    for (label, value, color), x in zip(metrics, positions):
        metric_svg.append(
            f'<rect x="{x}" y="84" width="190" height="108" rx="12" fill="#161b22" stroke="#30363d"/>'
            f'<text x="{x+18}" y="126" class="metric" fill="{color}">{short(int(value))}</text>'
            f'<text x="{x+18}" y="157" class="label">{label}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="550" viewBox="0 0 900 550">
<style>
  .title {{ font: 700 24px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#f0f6fc; }}
  .subtitle {{ font: 400 13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#8b949e; }}
  .metric {{ font: 700 34px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  .label {{ font: 600 10.5px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#8b949e; letter-spacing:.55px; }}
  .section {{ font: 700 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#f0f6fc; }}
  .release {{ font: 600 15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#c9d1d9; }}
  .lang {{ font: 600 13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#c9d1d9; }}
  .pct {{ font: 600 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; fill:#8b949e; text-anchor:end; }}
</style>
<rect width="100%" height="100%" rx="16" fill="#0d1117" stroke="#30363d"/>
<text x="35" y="45" class="title">⚡ Development Stats</text>
<text x="35" y="68" class="subtitle">Building activity from GitHub — no popularity grade</text>
{''.join(metric_svg)}
<rect x="35" y="210" width="830" height="86" rx="12" fill="#161b22" stroke="#30363d"/>
<text x="55" y="240" class="label">LATEST RELEASE</text>
<text x="55" y="269" class="release">{esc(latest_name)}</text>
<text x="835" y="269" class="subtitle" text-anchor="end">{esc(latest_date)}</text>
<text x="35" y="331" class="section">🎨 Repository Language Activity</text>
{''.join(rows)}
<text x="35" y="535" class="subtitle">Commits included in contributions this year: {short(commits)}</text>
<text x="865" y="535" class="subtitle" text-anchor="end">Updated automatically by GitHub Actions</text>
</svg>'''

def main():
    repos = get_repos()
    contributions, commits, prs = get_contribution_stats()
    releases, latest = get_release_data(repos)
    languages = get_languages(repos)
    svg = render_svg(len(repos), contributions, commits, prs, releases, latest, languages)
    output = Path("assets/development-stats.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    print(f"Wrote {output}")

if __name__ == "__main__":
    main()

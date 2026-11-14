"""Collect repos that depend on import-linter from GitHub's public dependents page.
Polite: 1 request / 2 s, resumable. Output: dependents.csv (repo, stars, forks)."""
import csv, re, sys, time, urllib.request, html as H
BASE = "https://github.com/seddonym/import-linter/network/dependents"
UA = {"User-Agent": "Mozilla/5.0 (academic research script)"}

def get(url):
    for _ in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "replace")
        except Exception as e:
            time.sleep(5)
    return None

def parse(h):
    out = []
    # each row is a div.Box-row; split on it
    for chunk in re.split(r'<div class="Box-row', h)[1:]:
        m = re.search(r'data-hovercard-type="repository"[^>]*href="/([^"/]+/[^"/]+)"', chunk)
        if not m: continue
        nums = re.findall(r'octicon-(?:star|repo-forked)[^>]*>.*?</svg>\s*([\d,]+)', chunk, re.S)
        stars = int(nums[0].replace(",", "")) if nums else 0
        forks = int(nums[1].replace(",", "")) if len(nums) > 1 else 0
        out.append((m.group(1), stars, forks))
    return out

url, rows, page = BASE, [], 0
while url and page < 120:
    h = get(url)
    if not h: print("fetch failed at page", page); break
    rows += parse(h); page += 1
    nxt = re.findall(r'href="([^"]*dependents_after=[^"]+)"', h)
    url = H.unescape(nxt[-1]) if nxt else None
    if page % 10 == 0: print("page", page, "rows", len(rows), flush=True)
    time.sleep(2)
seen, uniq = set(), []
for r in rows:
    if r[0] not in seen: seen.add(r[0]); uniq.append(r)
with open("dependents.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["repo", "stars", "forks"]); w.writerows(uniq)
print("done:", len(uniq), "unique repos from", page, "pages")

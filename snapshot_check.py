#!/usr/bin/env python3
"""Check real OpenAlex snapshot files for the same damage. No API key needed.

    python3 snapshot_check.py

Reads the first 70 MB of three public works files and writes
results/snapshot_check.txt. Downloads about 210 MB.
"""
import json
import os
import random
import unicodedata as ud
import urllib.request
import zlib

BUCKET = "https://openalex.s3.amazonaws.com"
SCRIPTS = ["DEVANAGARI", "THAI", "BENGALI", "TAMIL"]
JOINERS = ("‌", "‍")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "snapshot_check.txt")


def marks(text):
    return sum(ud.category(c).startswith("M") for c in text or "")


def read_records(url):
    req = urllib.request.Request(url, headers={"Range": "bytes=0-70000000"})
    raw = urllib.request.urlopen(req, timeout=180).read()
    text = zlib.decompressobj(31).decompress(raw).decode("utf8", "ignore")
    return text.split("\n")[:-1]


def main():
    with urllib.request.urlopen(f"{BUCKET}/data/jsonl/works/manifest.json", timeout=60) as r:
        manifest = json.load(r)
    files = sorted((f for f in manifest["files"] if f["meta"]["record_count"] >= 200000),
                   key=lambda f: f["url"])
    random.seed(3)
    chosen = [files[-1], files[len(files) // 2], random.choice(files)]

    lines = [f"Snapshot date: {manifest.get('date')}"]
    records = 0
    titles = dict.fromkeys(SCRIPTS, 0)
    titles_with_marks = dict.fromkeys(SCRIPTS, 0)
    abstracts_with_marks = 0
    author_names = 0
    author_names_with_marks = 0
    titles_with_joiner = 0
    abstracts_with_joiner = 0
    for entry in chosen:
        lines.append("File: " + entry["url"].replace("s3://openalex/", ""))
        for line in read_records(entry["url"].replace("s3://openalex", BUCKET)):
            try:
                work = json.loads(line)
            except ValueError:
                continue
            records += 1
            title = work.get("title") or work.get("display_name") or ""
            titles_with_joiner += any(j in title for j in JOINERS)
            abstracts_with_joiner += any(j in word for word in work.get("abstract_inverted_index") or {}
                                         for j in JOINERS)
            for script in SCRIPTS:
                if any(script in ud.name(c, "") for c in title if c.isalpha()):
                    titles[script] += 1
                    titles_with_marks[script] += marks(title) > 0
                    abstract = work.get("abstract_inverted_index") or {}
                    abstracts_with_marks += any(marks(word) > 0 for word in abstract)
                    for authorship in work.get("authorships") or []:
                        name = (authorship.get("author") or {}).get("display_name") or ""
                        if any(script in ud.name(c, "") for c in name if c.isalpha()):
                            author_names += 1
                            author_names_with_marks += marks(name) > 0
                    break
    lines.append(f"Records read: {records:,}")
    for script in SCRIPTS:
        lines.append(f"{script}: {titles[script]} titles, {titles_with_marks[script]} with any mark")
    lines.append(f"Those works whose abstract kept its marks: {abstracts_with_marks}")
    lines.append(f"Author names on those works in the same script: {author_names}, "
                 f"{author_names_with_marks} with marks")
    lines.append(f"All records: {titles_with_joiner} titles with a zero-width joiner, "
                 f"{abstracts_with_joiner} abstracts with one")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reproduce every table in README.md against the live OpenAlex API.

    OPENALEX_API_KEY=your_key python3 reproduce.py

Standard library only. One run costs about $0.35 of the free $1.00 daily budget.
Writes CSV files to results/ and prints a summary. A failed API call is counted
as an error, never as a miss.
"""
import csv
import datetime
import html
import json
import os
import re
import time
import unicodedata as ud
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.openalex.org"
KEY = os.environ["OPENALEX_API_KEY"]
AGENT = {"User-Agent": "openalex-title-marks-reproduce"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")

AFFECTED = ["hi", "th", "bn", "ta"]
CONTROLS = ["ar", "ko", "ru", "zh", "en"]
SCRIPT = {"hi": "DEVANAGARI", "th": "THAI", "bn": "BENGALI", "ta": "TAMIL", "ar": "ARABIC",
          "ko": "HANGUL", "ru": "CYRILLIC", "zh": "CJK", "en": "LATIN"}
NAMES = {"hi": "Hindi", "th": "Thai", "bn": "Bengali", "ta": "Tamil", "ar": "Arabic",
         "ko": "Korean", "ru": "Russian", "zh": "Chinese", "en": "English"}

WORDS = {
    "marks": [("Thai", "การศึกษา"), ("Thai", "การพัฒนา"), ("Thai", "นักเรียน"), ("Thai", "ผู้บริหาร"),
              ("Hindi", "शिक्षा"), ("Hindi", "विकास"), ("Hindi", "भारत"), ("Hindi", "साहित्य"),
              ("Bengali", "শিক্ষা"), ("Bengali", "বাংলাদেশ"), ("Tamil", "கல்வி"), ("Tamil", "தமிழ்"),
              ("Marathi", "शिक्षण"), ("Gujarati", "શિક્ષણ"), ("Kannada", "ಶಿಕ್ಷಣ"), ("Sinhala", "අධ්යාපන"),
              ("Punjabi", "ਸਿੱਖਿਆ"), ("Malayalam", "വിദ്യാഭ്യാസം"), ("Telugu", "విద్య")],
    "same_script_no_marks": [("Thai", "ประเทศไทย"), ("Thai", "ภาษาไทย"), ("Hindi", "नगर"),
                             ("Hindi", "समय"), ("Bengali", "নগর"), ("Tamil", "நகர")],
    "other_script": [("Arabic", "التعليم"), ("Chinese", "教育"), ("Korean", "교육"),
                     ("Russian", "образование"), ("English", "education")],
}


def api(path):
    """Return (json, status). The URL holds the key, so it is never printed."""
    sep = "&" if "?" in path else "?"
    req = urllib.request.Request(f"{API}{path}{sep}api_key={KEY}", headers=AGENT)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r), r.status
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return None, e.code
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
            return None, 0


def q(text):
    return urllib.parse.quote(text)


def marks(text):
    return sum(ud.category(c).startswith("M") for c in text or "")


def remove_marks(text):
    return "".join(c for c in text if not ud.category(c).startswith("M"))


def has_script(text, script):
    return any(script in ud.name(c, "") for c in text if c.isalpha())


def sanitize_name(text):
    """Python equivalent of sanitize_name in openalex-walden.

    Keeps Unicode categories L, N, P, S and Z, the pattern
    [^\\p{L}\\p{N}\\p{P}\\p{S}\\p{Z}], then collapses whitespace and trims.
    """
    kept = "".join(c for c in text if ud.category(c)[0] in "LNPSZ")
    return re.sub(r"[ \t\n\x0b\f\r]+", " ", kept).strip(" ")


def crossref_title(doi):
    """The title the publisher registered with Crossref, or None."""
    bare = doi.replace("https://doi.org/", "")
    url = "https://api.crossref.org/works/" + urllib.parse.quote(bare, safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=25) as r:
            titles = json.load(r)["message"].get("title") or []
    except Exception:
        return None
    if not titles:
        return None
    text = html.unescape(html.unescape(titles[0]))
    text = re.sub(r"</?[A-Za-z][A-Za-z0-9:-]*>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def count(path):
    data, status = api(path)
    return data["meta"]["count"] if data else f"ERROR {status}"


def title_hits(word):
    return count(f"/works?filter=title.search:{q(word)}&per_page=1&select=id")


def write_csv(name, header, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def spelling_test():
    rows = []
    for group, words in WORDS.items():
        for language, word in words:
            stripped = remove_marks(word)
            correct = title_hits(word)
            removed = "same word" if stripped == word else title_hits(stripped)
            rows.append([group, language, word, marks(word), correct, removed])
    write_csv("spelling_test.csv", ["group", "language", "word", "marks_in_word",
                                    "title_hits_correct_spelling", "title_hits_marks_removed"], rows)
    return rows


def route_test():
    routes = {
        "filter title.search": lambda w: title_hits(w),
        "filter title.search.exact": lambda w: count(f"/works?filter=title.search.exact:{q(w)}&per_page=1&select=id"),
        "filter display_name.search": lambda w: count(f"/works?filter=display_name.search:{q(w)}&per_page=1&select=id"),
        "OQL: works where title has": lambda w: count(f"/?oql={q('works where title has ' + w)}&per_page=1"),
        "autocomplete": lambda w: count(f"/autocomplete/works?q={q(w)}"),
        "filter title_and_abstract.search": lambda w: count(f"/works?filter=title_and_abstract.search:{q(w)}&per_page=1&select=id"),
        "search=": lambda w: count(f"/works?search={q(w)}&per_page=1&select=id"),
    }
    rows = []
    for word in ("शिक्षा", "การศึกษา"):
        for name, run in routes.items():
            rows.append([word, name, run(word), run(remove_marks(word))])
    write_csv("route_test.csv", ["word", "route", "hits_correct_spelling", "hits_marks_removed"], rows)
    return rows


def clean_query(title):
    text = re.sub(r"[\"':,|()\[\]{}!?*~^/\\<>=&+%#;]", " ", title)
    return re.sub(r"\s+", " ", text).strip()


def found(path, work_id):
    data, status = api(path)
    if data is None:
        return f"ERROR {status}"
    return any(r["id"] == work_id for r in data.get("results", []))


def pick_works(language, want, seed_start, max_lookups):
    """Random works whose Crossref title is in the expected script."""
    script = SCRIPT[language]
    picked, lookups, seed = [], 0, seed_start
    while len(picked) < want and lookups < max_lookups and seed < seed_start + 5:
        data, _ = api(f"/works?filter=language:{language},has_doi:true&sample=60&seed={seed}"
                      "&per_page=60&select=id,doi,display_name")
        seed += 1
        for work in (data or {}).get("results", []):
            if len(picked) >= want or lookups >= max_lookups:
                break
            name = work.get("display_name")
            if not work.get("doi") or not name or not has_script(name, script):
                continue
            lookups += 1
            title = crossref_title(work["doi"])
            time.sleep(0.05)
            if not title or not has_script(title, script) or not 12 <= len(title) <= 140:
                continue
            if language in AFFECTED and marks(title) == 0:
                continue
            picked.append((work, title))
    return picked


def real_title_test():
    rows = []
    for language in AFFECTED + CONTROLS:
        for work, title in pick_works(language, 12, 31, 70):
            query = q(clean_query(title))
            work_id = work["id"]
            rows.append([
                NAMES[language], work_id, work["doi"], title, work["display_name"],
                marks(title) > 0 and marks(work["display_name"]) == 0,
                found(f"/works?search={query}&per_page=25&select=id", work_id),
                found(f"/works?filter=title.search:{query}&per_page=25&select=id", work_id),
                found(f"/works?search.semantic={q(title[:200])}&per_page=25&select=id", work_id)
                if language in AFFECTED else "not run",
            ])
    write_csv("real_title_test.csv", ["language", "work", "doi", "crossref_title", "openalex_title",
                                      "title_damaged", "found_by_search", "found_by_title_search",
                                      "found_by_semantic_search"], rows)
    return rows


def sanitize_replay():
    rows = []
    for language in AFFECTED + CONTROLS:
        for work, title in pick_works(language, 15, 41, 45):
            openalex = work["display_name"]
            rows.append([NAMES[language], work["id"], title, openalex, sanitize_name(title) == openalex,
                         title == openalex])
    write_csv("sanitize_replay.csv", ["language", "work", "crossref_title", "openalex_title",
                                      "sanitize_output_equals_openalex", "crossref_equals_openalex"], rows)
    return rows


def tally(rows, language_col, value_col):
    """{language: (true count, total, error count)}"""
    out = {}
    for row in rows:
        yes, total, errors = out.get(row[language_col], (0, 0, 0))
        value = row[value_col]
        if isinstance(value, str) and value.startswith("ERROR"):
            errors += 1
        elif value is True:
            yes += 1
        if value != "not run":
            total += 1
        out[row[language_col]] = (yes, total, errors)
    return out


def main():
    used = lambda: (api("/rate-limit")[0] or {}).get("rate_limit", {}).get("daily_used_usd")
    before = used()
    print("Run date:", datetime.date.today().isoformat())

    print("\nSpelling test (group, language, word, correct, marks removed)")
    for row in spelling_test():
        print(" ", row[0], row[1], row[2], row[4], row[5])

    print("\nSearch routes (word, route, correct, marks removed)")
    for row in route_test():
        print(" ", *row)

    real = real_title_test()
    print("\nReal titles: language, tested, damaged, search=, title.search, semantic, errors")
    damaged = tally(real, 0, 5)
    by_search = tally(real, 0, 6)
    by_title = tally(real, 0, 7)
    by_semantic = tally(real, 0, 8)
    for name, (yes, total, _) in damaged.items():
        semantic = by_semantic.get(name, (0, 0, 0))
        errors = by_search[name][2] + by_title[name][2] + semantic[2]
        print(f"  {name}: {total}, {yes}, {by_search[name][0]}, {by_title[name][0]}, "
              f"{semantic[0] if semantic[1] else 'not run'}, {errors}")

    replay = sanitize_replay()
    print("\nReplay: language, titles, sanitize output equals OpenAlex, Crossref equals OpenAlex")
    equal = tally(replay, 0, 4)
    untouched = tally(replay, 0, 5)
    for name, (yes, total, _) in equal.items():
        print(f"  {name}: {total}, {yes}, {untouched[name][0]}")
    for row in replay:
        if not row[4]:
            print("  differs:", row[0], row[1], "|", row[2][:44], "|", row[3][:44])

    print(f"\nBudget used by this run: ${(used() or 0) - (before or 0):.3f}")


if __name__ == "__main__":
    main()

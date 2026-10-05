#!/usr/bin/env python3
"""Validate the App Store Connect text in this folder before anything is typed into the web UI.

    python3 validate_store_text.py

Rules (Arizona playbook 12.9 and 12.10, plus Apple's field limits):
  * lengths: name 30, subtitle 30, promotional text 170, keywords 100, description 4000, review notes 4000
  * no em dash or en dash anywhere (a family style rule; typing into the web UI has also silently dropped them)
  * keywords are comma separated with no spaces, no repeats, and do not repeat words from the app name
  * no stray leading or trailing whitespace, no tab characters, no curly quotes that the web form mangles
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIMITS = {"name.txt": 30, "subtitle.txt": 30, "promotional.txt": 170, "keywords.txt": 100, "description.txt": 4000, "review-notes.txt": 4000}
BANNED = {"—": "em dash", "–": "en dash", "‘": "curly quote", "’": "curly quote", "“": "curly quote", "”": "curly quote", "\t": "tab"}

problems = []
texts = {}
for name, limit in LIMITS.items():
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        problems.append(f"{name}: missing")
        continue
    text = open(path, encoding="utf-8").read()
    texts[name] = text
    body = text.rstrip("\n")
    if body != body.strip():
        problems.append(f"{name}: leading or trailing whitespace")
    if len(body) > limit:
        problems.append(f"{name}: {len(body)} characters, limit {limit}")
    for ch, label in BANNED.items():
        if ch in body:
            problems.append(f"{name}: contains a {label}")
    print(f"{name:18s} {len(body):5d} / {limit}")

kw = texts.get("keywords.txt", "").strip()
if kw:
    items = kw.split(",")
    if ", " in kw or any(i != i.strip() or not i for i in items):
        problems.append("keywords.txt: use commas with no spaces and no empty entries")
    lowered = [i.lower() for i in items]
    if len(set(lowered)) != len(lowered):
        problems.append("keywords.txt: repeated keyword")
    name_words = set(re.findall(r"[a-z]+", texts.get("name.txt", "").lower()))
    clash = [i for i in lowered if set(re.findall(r"[a-z]+", i)) <= name_words and i]
    if clash:
        problems.append(f"keywords.txt: repeats words already in the app name: {clash}")

if problems:
    print()
    for p in problems:
        print("FAIL:", p)
    sys.exit(1)
print("PASS: all store text is within limits and clean")

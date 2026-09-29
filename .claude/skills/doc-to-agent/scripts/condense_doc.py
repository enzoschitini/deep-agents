"""Condense a Mintlify/MDX documentation page so it can be read in full.

LangChain docs repeat the same example once per model provider (Google, OpenAI,
Anthropic, OpenRouter, ...) inside <CodeGroup> or <Tabs>. Those variants differ only
in the model string, yet they can make up most of the page. This script keeps one
variant (Anthropic when present), drops the near-identical copies, and leaves every
other line of prose, notes and code untouched — so reading the condensed file is
reading the whole doc.

Usage:
  python condense_doc.py <doc.md>                  condensed doc to stdout
  python condense_doc.py <doc.md> -o <out.md>      condensed doc to a file; the
                                                   outline and stats go to stdout
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

FENCE = re.compile(r"^(\s*)(`{3,})(.*)$")
THEME = re.compile(r"\s*theme=\{.*\}\s*$")
OPEN = re.compile(r"^\s*<(CodeGroup|Tabs)(\s[^>]*)?>\s*$")
TAB_OPEN = re.compile(r'^\s*<Tab\s+title="([^"]*)"[^>]*>\s*$')
TAB_CLOSE = re.compile(r"^\s*</Tab>\s*$")
IMG = re.compile(r'<img\s[^>]*?alt="([^"]*)"[^>]*/?>')
DIV = re.compile(r"^\s*</?div(\s[^>]*)?>\s*$")
MODEL_STRING = re.compile(r"""(["'])[a-z_]+:[^"'\s]+\1""")
HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
DOC_LINK = re.compile(r"\]\((/[^)#\s]+)")

SIMILAR = 0.9  # provider variants score ~1.0 once model strings are masked


def _fence_end(lines: list[str], i: int) -> int:
    """Index of the line closing the code fence opened at lines[i]."""
    ticks = FENCE.match(lines[i]).group(2)
    for j in range(i + 1, len(lines)):
        m = FENCE.match(lines[j])
        if m and m.group(2) == ticks and not m.group(3).strip():
            return j
    return len(lines) - 1


def _block_end(lines: list[str], i: int, tag: str) -> int:
    """Index of the </tag> matching the <tag> at lines[i], skipping code fences."""
    depth, j = 0, i
    while j < len(lines):
        if FENCE.match(lines[j]):
            j = _fence_end(lines, j) + 1
            continue
        if re.match(rf"^\s*<{tag}(\s[^>]*)?>\s*$", lines[j]):
            depth += 1
        elif re.match(rf"^\s*</{tag}>\s*$", lines[j]):
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(lines) - 1


def _children(lines: list[str], tag: str) -> list[tuple[str, list[str]]]:
    """Split the body of a <CodeGroup> into code fences, or of <Tabs> into <Tab>s."""
    out, i = [], 0
    while i < len(lines):
        if tag == "CodeGroup" and FENCE.match(lines[i]):
            j = _fence_end(lines, i)
            label = FENCE.match(lines[i]).group(3).strip().split(" ", 1)
            out.append((label[1] if len(label) > 1 else label[0], lines[i : j + 1]))
            i = j + 1
        elif tag == "Tabs" and TAB_OPEN.match(lines[i]):
            j = _block_end(lines, i, "Tab")
            out.append((TAB_OPEN.match(lines[i]).group(1), lines[i : j + 1]))
            i = j + 1
        else:
            i += 1
    return out


def _normalized(block: list[str]) -> str:
    return MODEL_STRING.sub('"<model>"', "\n".join(line.strip() for line in block))


def _dedupe(children, stats) -> list[str]:
    """Keep one of each group of near-identical variants, preferring Anthropic."""
    order = sorted(range(len(children)), key=lambda k: "anthropic" not in children[k][0].lower())
    kept, dropped = [], []
    for k in order:
        text = _normalized(children[k][1])
        if any(difflib.SequenceMatcher(None, text, _normalized(children[q][1])).ratio() >= SIMILAR for q in kept):
            dropped.append(children[k][0])
        else:
            kept.append(k)
    out = [line for k in sorted(kept) for line in children[k][1]]
    if dropped:
        stats["collapsed"] += len(dropped)
        out.append(f"<!-- condensed: {len(dropped)} near-identical variant(s) omitted: {', '.join(dropped)} -->")
    return out


def condense(lines: list[str], stats: dict) -> list[str]:
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            j = _fence_end(lines, i)
            out.append(THEME.sub("", line))
            out.extend(lines[i + 1 : j + 1])
            i = j + 1
            continue
        m = OPEN.match(line)
        if m:
            tag = m.group(1)
            j = _block_end(lines, i, tag)
            body = condense(lines[i + 1 : j], stats)  # innermost groups first
            children = _children(body, tag)
            out.append(line)
            out.extend(_dedupe(children, stats) if len(children) > 1 else body)
            out.append(lines[j])
            i = j + 1
            continue
        if DIV.match(line):
            i += 1
            continue
        out.append(IMG.sub(lambda mm: f"[image: {mm.group(1)}]", line))
        i += 1
    return out


def outline(lines: list[str]) -> list[str]:
    rows, in_fence = [], False
    for n, line in enumerate(lines, 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        m = HEADING.match(line)
        if m and not in_fence:
            rows.append(f"{n:>5}  {'  ' * (len(m.group(1)) - 1)}{m.group(2)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("doc", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="write the condensed doc here")
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    source = args.doc.read_text(encoding="utf-8").splitlines()
    stats = {"collapsed": 0}
    result = condense(source, stats)
    text = "\n".join(result) + "\n"

    if not args.output:
        sys.stdout.write(text)
        return

    args.output.write_text(text, encoding="utf-8")
    links = sorted(set(DOC_LINK.findall("\n".join(source))))
    print(f"source     {args.doc}  ({len(source)} lines)")
    print(f"condensed  {args.output}  ({len(result)} lines, {stats['collapsed']} duplicate variants omitted)")
    print("\noutline (line numbers in the condensed file):")
    print("\n".join(outline(result)))
    if links:
        print("\nlinks to other doc pages (out of scope unless this page depends on them):")
        print("\n".join(f"  {link}" for link in links))


if __name__ == "__main__":
    main()

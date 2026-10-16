#!/usr/bin/env python3
"""Render eval grader templates from fixture ground truth.

Every eval case directory may hold ``graders/<name>.md.tmpl`` files. A template
is the grader Markdown with ``{{expected.<dotted.path>}}`` placeholders that are
resolved against the ``expected.json`` of the fixture the case declares. The
rendered ``graders/<name>.md`` is committed next to the template, so a grader
never carries a hand-typed number and a fixture change shows up as a diff.

Templates in ``<evals dir>/graders-shared/`` are rendered into every case that
has a ``graders/`` directory and a known fixture (the safety grader every
fixture-backed case must carry). A case-local template of the same name wins.

The fixture of a case is read, in this order, from:

1. ``fixture: <name>`` in the case's ``case.yaml`` top-level ``metadata`` block,
   written as a line ``  fixture: <name>`` (a plain scan, no YAML parser);
2. a ``fixture`` file in the case directory holding the name;
3. the ``-<name>`` suffix of the case directory for a known fixture name.

Path lookups: ``expected.entities.node.article.distinct``. Dict keys and list
indexes are separated by dots; a key containing a dot is not supported (none
does). Numbers render as JSON would print them (``12``, ``50.0``); lists and
objects render as compact JSON. ``{{expected.<path>|regex}}`` renders the value
escaped for use inside a regular expression.

Usage:
    render-cases.py [--check] [--evals-dir DIR] [CASE_DIR ...]

Standard library only; ``python3 -I`` safe. Exit 1 on a missing key, an
unknown fixture, or (with ``--check``) any rendered file that differs from the
template output or is missing.
"""

import argparse
import json
import re
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = EVALS_DIR / "fixtures"
SHARED_DIR_NAME = "graders-shared"
PLACEHOLDER = re.compile(r"\{\{\s*expected\.([A-Za-z0-9_.\-]+)\s*(?:\|\s*(regex)\s*)?\}\}")


def fixture_names():
    return sorted(p.parent.name for p in FIXTURES_DIR.glob("*/spec.json"))


def case_fixture(case_dir):
    case_yaml = case_dir / "case.yaml"
    if case_yaml.is_file():
        match = re.search(r"^\s*fixture:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$", case_yaml.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    marker = case_dir / "fixture"
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip()
    for name in fixture_names():
        if case_dir.name.endswith("-" + name):
            return name
    return None


def lookup(data, dotted):
    node = data
    for part in dotted.split("."):
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                raise KeyError(dotted)
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(dotted)
    return node


def render_value(value, mode):
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = json.dumps(value)
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if mode == "regex":
        return re.escape(text)
    return text


def render_template(text, expected, where):
    missing = []

    def replace(match):
        path, mode = match.group(1), match.group(2)
        try:
            return render_value(lookup(expected, path), mode)
        except KeyError:
            missing.append(path)
            return match.group(0)

    rendered = PLACEHOLDER.sub(replace, text)
    if missing:
        raise KeyError("%s: expected.json has no key %s" % (where, ", ".join(sorted(set(missing)))))
    # The runner reads the frontmatter from the very first line, so the provenance
    # note goes inside it as a YAML comment, never before the opening `---`.
    note = "# Rendered by evals/scripts/render-cases.py from %s; edit the template, not this file.\n" % where.name
    if rendered.startswith("---\n"):
        return "---\n" + note + rendered[len("---\n"):]
    raise KeyError("%s: template must start with a `---` frontmatter line" % where)


def case_dirs(evals_dir, requested):
    if requested:
        return [Path(p).resolve() for p in requested]
    found = set()
    for graders in evals_dir.rglob("graders"):
        if not graders.is_dir() or "fixtures" in graders.parts or "results" in graders.parts:
            continue
        found.add(graders.parent)
    return sorted(found)


def templates_for(case_dir, evals_dir, fixture):
    """Case-local templates plus the shared ones a fixture-backed case inherits."""
    local = {t.name: t for t in (case_dir / "graders").glob("*.md.tmpl")}
    shared = {}
    if fixture is not None:
        shared = {t.name: t for t in (evals_dir / SHARED_DIR_NAME).glob("*.md.tmpl")}
    merged = dict(shared)
    merged.update(local)
    return [merged[name] for name in sorted(merged)]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case directories (default: every case with a graders/*.md.tmpl)")
    parser.add_argument("--check", action="store_true", help="exit 1 when a rendered grader differs from its template output")
    parser.add_argument("--evals-dir", default=str(EVALS_DIR), help="eval directory to scan (default: the one holding this script)")
    args = parser.parse_args(argv)
    evals_dir = Path(args.evals_dir).resolve()
    ok = True
    rendered_count = 0
    expected_cache = {}
    for case_dir in case_dirs(evals_dir, args.cases):
        fixture = case_fixture(case_dir)
        if fixture is not None and not (FIXTURES_DIR / fixture / "expected.json").is_file():
            fixture = None
        templates = templates_for(case_dir, evals_dir, fixture)
        if not templates:
            continue
        if fixture is None:
            print("%s: cannot determine the fixture (declare `fixture:` in case.yaml or name the case <skill>-<fixture>)" % case_dir)
            ok = False
            continue
        if fixture not in expected_cache:
            expected_cache[fixture] = json.loads((FIXTURES_DIR / fixture / "expected.json").read_text(encoding="utf-8"))
        expected = expected_cache[fixture]
        for tmpl in templates:
            target = case_dir / "graders" / tmpl.name[: -len(".tmpl")]
            try:
                output = render_template(tmpl.read_text(encoding="utf-8"), expected, tmpl)
            except KeyError as exc:
                print(exc)
                ok = False
                continue
            rel = target.relative_to(evals_dir)
            if args.check:
                if not target.is_file():
                    print("%s: missing (run render-cases.py)" % rel)
                    ok = False
                elif target.read_text(encoding="utf-8") != output:
                    print("%s: differs from its template output (run render-cases.py)" % rel)
                    ok = False
            else:
                target.write_text(output, encoding="utf-8")
                rendered_count += 1
    if args.check:
        print("render-cases: %s" % ("all rendered graders up to date" if ok else "stale or broken graders found"))
    else:
        print("render-cases: wrote %d grader file(s)" % rendered_count)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

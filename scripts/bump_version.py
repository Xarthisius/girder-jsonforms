#!/usr/bin/env python3
"""Bump the version of girder-jsonforms in every place that records it.

Four tracked files carry the version, and they have drifted from each other in
the past because nothing ties them together:

  pyproject.toml                               [project] version  (the wheel/sdist)
  uv.lock                                      the editable self-entry
  girder_jsonforms/web_client/package.json     npm package version
  girder_jsonforms/web_client/package-lock.json  root + packages[""] entries

The fifth place is the git tag ``vX.Y.Z``: pushing it is what makes
``.github/workflows/release.yml`` build and publish to PyPI, so the tag has to
agree with pyproject.toml or the release is mislabelled.

Usage::

    scripts/bump_version.py --check        # report the four, exit 1 if they disagree
    scripts/bump_version.py patch          # 2.1.2 -> 2.1.3
    scripts/bump_version.py minor          # 2.1.2 -> 2.2.0
    scripts/bump_version.py 2.4.0          # explicit
    scripts/bump_version.py patch -n       # dry run, show the diff it would make
    scripts/bump_version.py patch --commit --tag

"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_CLIENT = ROOT / "girder_jsonforms" / "web_client"

PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PACKAGE_JSON = WEB_CLIENT / "package.json"
PACKAGE_LOCK = WEB_CLIENT / "package-lock.json"

# Plain X.Y.Z only: it has to be valid for both PEP 440 and npm's semver, and
# the two disagree on how to spell anything fancier (2.2.0rc1 vs 2.2.0-rc.1).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# [project] version in pyproject.toml -- anchored to the table so a version in
# some other table can't be hit instead.
PYPROJECT_RE = re.compile(
    r'(?ms)^(\[project\].*?^version\s*=\s*")(?P<version>[^"]+)(")'
)

# The plugin's own [[package]] entry in uv.lock, not any of its dependencies.
UV_LOCK_RE = re.compile(
    r'(?ms)^(name = "girder-jsonforms"\nversion = ")(?P<version>[^"]+)(")'
)

# First "version" line of package.json / package-lock.json is the top-level
# one; in the lock file the second is packages[""]. Both are verified by
# re-parsing the JSON after the edit, so position is checked, not trusted.
JSON_VERSION_RE = re.compile(r'(?m)^(\s*"version":\s*")(?P<version>[^"]*)(")')


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def read_versions():
    """Return {label: (path, version)} for every file that records one."""
    pyproject = PYPROJECT.read_text()
    uv_lock = UV_LOCK.read_text()

    match = PYPROJECT_RE.search(pyproject)
    if not match:
        fail(f"no [project] version found in {PYPROJECT}")
    uv_match = UV_LOCK_RE.search(uv_lock)
    if not uv_match:
        fail(f'no [[package]] entry for girder-jsonforms in {UV_LOCK}')

    lock = json.loads(PACKAGE_LOCK.read_text())
    return {
        "pyproject.toml": (PYPROJECT, match.group("version")),
        "uv.lock": (UV_LOCK, uv_match.group("version")),
        "package.json": (
            PACKAGE_JSON,
            json.loads(PACKAGE_JSON.read_text()).get("version"),
        ),
        "package-lock.json": (PACKAGE_LOCK, lock.get("version")),
        'package-lock.json packages[""]': (
            PACKAGE_LOCK,
            lock.get("packages", {}).get("", {}).get("version"),
        ),
    }


def git(*args, capture=False):
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        fail(f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def next_version(current, part):
    major, minor, patch = (int(piece) for piece in current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def substitute(pattern, text, new_version, count, path):
    text, made = pattern.subn(rf"\g<1>{new_version}\g<3>", text, count=count)
    if made != count:
        fail(f"expected {count} version replacement(s) in {path}, made {made}")
    return text


def write(path, text, dry_run):
    if dry_run:
        return
    path.write_text(text)


def main():
    parser = argparse.ArgumentParser(
        description="Bump girder-jsonforms' version everywhere it is recorded.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage::", 1)[1] if "Usage::" in __doc__ else None,
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="X.Y.Z, or one of major/minor/patch to derive it from pyproject.toml",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report the recorded versions; exit 1 if they disagree",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show what would change without writing anything",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="git commit the four files (no push)",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="create the annotated vX.Y.Z tag (implies --commit; no push)",
    )
    args = parser.parse_args()

    versions = read_versions()
    current = versions["pyproject.toml"][1]

    if args.check or not args.version:
        width = max(len(label) for label in versions)
        for label, (_, version) in versions.items():
            flag = "" if version == current else "   <- differs"
            print(f"  {label:<{width}}  {version}{flag}")
        disagree = [v for _, (_, v) in versions.items() if v != current]
        if args.check:
            if disagree:
                print(
                    "\nversions disagree; "
                    f"run {Path(__file__).name} {current} to resync them",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"\nall in sync at {current}")
            return
        parser.error("a version (X.Y.Z, major, minor or patch) is required")

    if args.version in ("major", "minor", "patch"):
        new_version = next_version(current, args.version)
    else:
        new_version = args.version
        if not VERSION_RE.match(new_version):
            fail(f"{new_version!r} is not a plain X.Y.Z version")

    print(f"{current} -> {new_version}\n")

    write(
        PYPROJECT,
        substitute(PYPROJECT_RE, PYPROJECT.read_text(), new_version, 1, PYPROJECT),
        args.dry_run,
    )
    write(
        UV_LOCK,
        substitute(UV_LOCK_RE, UV_LOCK.read_text(), new_version, 1, UV_LOCK),
        args.dry_run,
    )
    write(
        PACKAGE_JSON,
        substitute(
            JSON_VERSION_RE, PACKAGE_JSON.read_text(), new_version, 1, PACKAGE_JSON
        ),
        args.dry_run,
    )
    write(
        PACKAGE_LOCK,
        substitute(
            JSON_VERSION_RE, PACKAGE_LOCK.read_text(), new_version, 2, PACKAGE_LOCK
        ),
        args.dry_run,
    )

    paths = [PYPROJECT, UV_LOCK, PACKAGE_JSON, PACKAGE_LOCK]
    relative = [str(path.relative_to(ROOT)) for path in paths]

    if args.dry_run:
        print("dry run, nothing written. Would have touched:")
        for path in relative:
            print(f"  {path}")
        git("--no-pager", "diff", "--stat", "--", *relative)
        return

    # Re-read: this is what makes the positional JSON edits safe.
    for label, (_, version) in read_versions().items():
        if version != new_version:
            fail(f"{label} is {version} after the edit, expected {new_version}")
    print("updated and verified:")
    for path in relative:
        print(f"  {path}")

    tag = f"v{new_version}"
    if args.commit or args.tag:
        git("commit", "-m", f"Bump version to {new_version}", "--", *relative)
        print(f"\ncommitted: Bump version to {new_version}")
    if args.tag:
        git("tag", "-a", tag, "-m", tag)
        print(f"tagged: {tag}")

    print("\nNext:")
    if not args.commit and not args.tag:
        print(f"  git commit -m 'Bump version to {new_version}' -- " + " ".join(relative))
    if not args.tag:
        print(f"  git tag -a {tag} -m {tag}")
    print(f"  git push origin HEAD && git push origin {tag}")
    print("  # pushing the tag is what publishes to PyPI (.github/workflows/release.yml)")


if __name__ == "__main__":
    main()

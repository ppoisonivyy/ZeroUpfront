"""Rebuild the release dependency tables from the locks, upstream metadata and a local image."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.request import urlopen
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "docs" / "third-party-packages.md"


def declared_license(info):
    expression = info.get("license_expression")
    if expression:
        return expression
    legacy = (info.get("license") or "").strip()
    if legacy and len(legacy) <= 160:
        return " ".join(legacy.split())
    classifiers = [s.rsplit(" :: ", 1)[-1] for s in info.get("classifiers", [])
                   if s.startswith("License ::") and not s.endswith("OSI Approved")]
    return " / ".join(classifiers) or "See upstream distribution license file"


def python_row(pkg, direct, dev):
    name, version = pkg["name"], pkg["version"]
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urlopen(url, timeout=25) as response:
        info = json.load(response)["info"]
    scope = []
    if name in direct:
        scope.append("direct runtime")
    if name in dev:
        scope.append("declared for development")
    if not scope:
        scope.append("transitive")
    license_text = declared_license(info).replace("|", " / ")
    return f"| [{name}](https://pypi.org/project/{name}/{version}/) | {version} | {', '.join(scope)} | {license_text} |"


def package_document():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pylock = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    py = sorted((p for p in pylock if "registry" in p["source"]), key=lambda p: p["name"])
    package_name = lambda dep: re.split(r"[\[<>=!~; ]", dep, maxsplit=1)[0]
    direct = {package_name(x) for x in config["project"]["dependencies"]}
    dev = {package_name(x) for x in config["dependency-groups"]["dev"]}
    npm = json.loads((ROOT / "web/package-lock.json").read_text())["packages"]
    root = npm[""]
    rows = ["# Locked application packages", "",
            "This catalog includes every registry package in both lockfiles, including development tools and "
            "platform-specific alternatives. A listed package may be used in more than one dependency group. "
            "The npm flags and the Python environment markers in the lockfiles determine what gets installed. "
            "License labels come from version-specific upstream metadata. The licenses distributed with the actual packages govern their use.", "",
            f"## Python · {len(py)} locked packages", "",
            "| Upstream release | Version | Relationship | Declared license |", "| --- | --- | --- | --- |"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows.extend(pool.map(lambda p: python_row(p, direct, dev), py))
    rows.extend(["", f"## Browser and build · {len(npm)-1} locked entries", "",
                 "| Upstream release | Version | Relationship | Declared license |", "| --- | --- | --- | --- |"])
    for path, pkg in sorted(npm.items()):
        if not path:
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        if name in root["dependencies"]:
            scope = "direct"
        elif name in root["devDependencies"]:
            scope = "direct build"
        else:
            scope = "transitive build" if pkg.get("dev") else "transitive"
        if pkg.get("optional"):
            scope += ", optional"
        rows.append(f"| [{name}](https://www.npmjs.com/package/{quote(name, safe='/@')}/v/{pkg['version']}) | "
                    f"{pkg['version']} | {scope} | {pkg.get('license','See upstream distribution')} |")
    return "\n".join(rows) + "\n"


def image_document(image):
    def run(command):
        return subprocess.check_output(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", command], text=True).strip()
    details = run("dpkg --print-architecture; python --version; uv --version").splitlines()
    packages = run("dpkg-query -W -f='${binary:Package}\\t${Version}\\n'").splitlines()
    libs = run("find /srv/zeroupfront/.venv -path '*.libs/*' -type f | sort").splitlines()
    rows = ["# Release container components", "",
            f"This snapshot covers the tested Debian Bookworm {details[0]} release, {details[1]} and {details[2]}. "
            "The Dockerfile also uses Node 24 to compile the browser bundle. Rebuild this inventory for another image or architecture. "
            "The image installs the Python runtime under /usr/local in addition to the Debian packages below.", "",
            f"## Debian packages · {len(packages)}", "",
            "| Package | Installed version | Notice path inside the image |", "| --- | --- | --- |"]
    for row in sorted(packages):
        name, version = row.split("\t")
        rows.append(f"| {name} | {version} | `/usr/share/doc/{name.split(':')[0]}/copyright` |")
    rows.extend(["", "## Native libraries shipped inside Python wheels", "",
                 "These shared objects are present outside Debian's package database. "
                 "The containing wheel identifies the distribution that supplies the binary.", "",
                 "| Wheel directory | Library file |", "| --- | --- |"])
    for path in sorted(libs):
        rows.append(f"| {Path(path).parent.name} | {Path(path).name} |")
    rows += ["", "For embedded or statically linked code, consult the upstream Python distribution notices "
             "and browser resource licenses in the [component inventory](../THIRD_PARTY.md).",""]
    return "\n".join(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Also record Debian packages and native wheel libraries from this built release.")
    args = parser.parse_args()
    TARGET.write_text(package_document())
    if args.image:
        (ROOT / "docs/release-components.md").write_text(image_document(args.image))

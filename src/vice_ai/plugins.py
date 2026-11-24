"""Third-party source packages that survive upgrades.

    vice plugin install <spec>...   add packages (PyPI name, name==1.2, path, git URL)
    vice plugin install --reinstall rebuild this Python's folder from the manifest
    vice plugin remove <name>
    vice plugin list

Packages go into ~/.vice/plugins/py<major>.<minor>/, which vice appends to sys.path. The specs
are recorded in ~/.vice/plugins.toml so the folder can be rebuilt (new Python, new vice).
Anything vice's own environment already provides is not installed again. Nothing is ever
installed implicitly: plugin code runs with your privileges inside the vice service.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path

from . import paths

GROUP = "vice.sources"


class PluginError(Exception):
    pass


def plugin_dir() -> Path:
    return paths.plugins_dir() / f"py{sys.version_info.major}.{sys.version_info.minor}"


def manifest_file() -> Path:
    return paths.home() / "plugins.toml"


def activate() -> None:
    """Append this Python's plugin folder to sys.path (end, so vice's own dependencies win)."""
    d = plugin_dir()
    s = str(d)
    if s not in sys.path and d.is_dir():
        sys.path.append(s)
        importlib.invalidate_caches()


# manifest

def load_manifest() -> list[str]:
    f = manifest_file()
    if not f.exists():
        return []
    import tomllib

    try:
        pk = tomllib.loads(f.read_text()).get("packages", [])
    except tomllib.TOMLDecodeError as e:
        raise PluginError(f"{f}: {e}") from e
    if not (isinstance(pk, list) and all(isinstance(x, str) for x in pk)):
        raise PluginError(f"{f}: packages must be a list of strings")
    return pk


def save_manifest(specs: list[str]) -> None:
    f = manifest_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"  {json.dumps(s)},\n" for s in specs)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(f"packages = [\n{body}]\n")
    os.replace(tmp, f)


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def canonical_spec(spec: str) -> str:
    """A path spec is stored absolute, so a rebuild from another directory finds it."""
    p = Path(spec).expanduser()
    return str(p.resolve()) if p.exists() else spec.strip()


def _spec_name(spec: str) -> str | None:
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:$|[\[=<>!~;@(])", spec)
    return norm(m.group(1)) if m and not re.match(r"^\w+://", spec) else None


def _dist_url(d: Distribution) -> str | None:
    try:
        return json.loads(d.read_text("direct_url.json") or "{}").get("url")
    except ValueError:
        return None


def spec_matches(spec: str, name: str, dists: list[Distribution] = ()) -> bool:
    """Does this manifest spec install the package called `name`?"""
    name = norm(name)
    if _spec_name(spec) == name:
        return True
    for d in dists:
        if norm(d.metadata["Name"] or "") != name:
            continue
        url = _dist_url(d)
        if url and (url in spec or (os.path.exists(spec) and Path(spec).resolve().as_uri() == url)):
            return True
    return False


# installed state

def plugin_dists(path: Path | None = None) -> list[Distribution]:
    d = path or plugin_dir()
    return list(distributions(path=[str(d)])) if d.is_dir() else []


def _eps(d: Distribution):
    return [ep for ep in d.entry_points if ep.group == GROUP]


def types_of(d: Distribution) -> list[str]:
    return [ep.name for ep in _eps(d)]


def load_error(ep) -> str | None:
    from .adapters.base import SourceAdapter

    try:
        cls = ep.load()
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    if not (isinstance(cls, type) and issubclass(cls, SourceAdapter)):
        return "not a SourceAdapter"
    return None


def installed() -> list[dict]:
    """Plugin packages in this Python's folder: name, version, {type: error or None}."""
    activate()
    out = []
    for d in plugin_dists():
        eps = _eps(d)
        if eps:
            out.append({"name": d.metadata["Name"], "version": d.version,
                        "types": {ep.name: load_error(ep) for ep in eps}})
    return sorted(out, key=lambda p: norm(p["name"]))


def status_lines() -> list[str]:
    lines = []
    for p in installed():
        bad = {t: e for t, e in p["types"].items() if e}
        lines.append(f"plugins: {p['name']} {p['version']}" + "".join(f"  FAILED {t}: {e}" for t, e in bad.items()))
    return lines


# resolving and installing

def _have_pip() -> bool:
    return importlib.util.find_spec("pip") is not None


def _run(cmd: list[str]) -> str:
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as e:
        raise PluginError(f"could not run {cmd[0]}: {e}") from e
    if r.returncode:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-12:])
        raise PluginError(f"{' '.join(cmd[:4])} failed:\n{tail}")
    return r.stdout + ("\n" + r.stderr if r.stderr else "")


def _backend() -> str:
    if _have_pip():
        return "pip"
    if shutil.which("uv"):
        return "uv"
    raise PluginError("neither pip nor uv is available for this vice install. "
                      "Install uv (https://docs.astral.sh/uv/) and retry, or run "
                      "`python -m ensurepip` in vice's environment.")


def _install_cmd(backend: str, target: Path, args: list[str]) -> list[str]:
    if backend == "pip":
        return [sys.executable, "-m", "pip", "install", "--no-deps", "--no-input", "-q", "--target", str(target), *args]
    return ["uv", "pip", "install", "--python", sys.executable, "--no-deps", "-q", "--target", str(target), *args]


def resolve(backend: str, specs: list[str]) -> list[tuple[str, str]]:
    """(name, version) pip would install for these specs into vice's own environment."""
    if backend == "pip":
        out = _run([sys.executable, "-m", "pip", "install", "--dry-run", "--report", "-", "--quiet",
                    "--no-input", "--break-system-packages", *specs])
        try:
            report = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except ValueError as e:
            raise PluginError("could not read pip's resolution report") from e
        return [(i["metadata"]["name"], i["metadata"]["version"]) for i in report.get("install", [])]
    out = _run(["uv", "pip", "install", "--dry-run", "--python", sys.executable, *specs])
    return re.findall(r"^\s*\+ (\S+)==(\S+)", out, re.M)


def env_provided() -> dict[str, str]:
    """name -> version of what vice's own environment provides (the plugin folder excluded)."""
    skip = str(paths.plugins_dir())
    found: dict[str, str] = {}
    for d in distributions(path=[p for p in sys.path if p and not p.startswith(skip)]):
        n = d.metadata["Name"]
        if n:
            found.setdefault(norm(n), d.version)
    return found


def missing_deps(resolved: list[tuple[str, str]], requested: set[str], provided: dict[str, str]) -> list[str]:
    """Pins for dependencies to install; raises when one conflicts with vice's environment."""
    pins = []
    for name, version in resolved:
        n = norm(name)
        if n in requested:
            continue
        if n in provided:
            raise PluginError(f"needs {name}=={version} but vice's environment has {name}=={provided[n]}")
        pins.append(f"{name}=={version}")
    return pins


def _build(specs: list[str], target: Path) -> dict[str, list[str]]:
    """Install specs and their missing dependencies into target. Returns spec -> dist names."""
    backend = _backend()
    target.mkdir(parents=True)
    names: dict[str, list[str]] = {}
    seen: set[str] = set()
    for s in specs:
        _run(_install_cmd(backend, target, [s]))
        now = {norm(d.metadata["Name"]) for d in plugin_dists(target)}
        names[s] = sorted(now - seen)
        seen = now
    if specs:
        pins = missing_deps(resolve(backend, specs), seen, env_provided())
        if pins:
            _run(_install_cmd(backend, target, pins))
    return names


def _swap(tmp: Path, final: Path) -> None:
    old = final.with_name(final.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        os.replace(final, old)
    try:
        os.replace(tmp, final)
    except OSError:
        if old.exists():
            os.replace(old, final)
        raise
    shutil.rmtree(old, ignore_errors=True)


def rebuild(specs: list[str], new: list[str] = ()) -> dict[str, list[str]]:
    """Make the plugin folder hold exactly specs. Every spec in `new` must register a source type.
    The working folder is replaced only when everything succeeded."""
    final = plugin_dir()
    tmp = final.with_name(f".{final.name}.tmp{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        names = _build(specs, tmp) if specs else {}
        by_name = {norm(d.metadata["Name"]): d for d in plugin_dists(tmp)}
        for s in new:
            if not any(_eps(by_name[n]) for n in names.get(s, []) if n in by_name):
                raise PluginError(f"{s} registers no source types (no {GROUP} entry point); not installed")
        if specs:
            _swap(tmp, final)
        else:
            shutil.rmtree(final, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return names


# commands

def _restart_note() -> None:
    from . import service

    if service.is_loaded():
        print("vice is running; restart it to load the change: vice stop && vice start")


def cmd_install(args) -> int:
    manifest = load_manifest()
    if args.reinstall:
        if args.specs:
            raise PluginError("--reinstall takes no packages")
        new: list[str] = []
        specs = manifest
        if not specs:
            print("plugins.toml lists no packages; nothing to rebuild.")
            return 0
    else:
        if not args.specs:
            raise PluginError("give at least one package, or --reinstall")
        new = [canonical_spec(s) for s in args.specs]
        specs = manifest + [s for s in new if s not in manifest]
    rebuild(specs, new)
    if not args.reinstall:
        save_manifest(specs)
    activate()
    for p in installed():
        print(f"{p['name']} {p['version']}: {', '.join(p['types'])}")
    _restart_note()
    return 0


def cmd_remove(args) -> int:
    manifest = load_manifest()
    dists = plugin_dists()
    keep = [s for s in manifest if not spec_matches(s, args.name, dists)]
    if len(keep) == len(manifest):
        raise PluginError(f"no plugin {args.name!r} in {manifest_file()}")
    rebuild(keep)
    save_manifest(keep)
    print(f"removed {args.name}")
    _restart_note()
    return 0


def cmd_list(args) -> int:
    manifest = load_manifest()
    pk = installed()
    for p in pk:
        bad = {t: e for t, e in p["types"].items() if e}
        state = "loads" if not bad else "FAILED: " + "; ".join(f"{t}: {e}" for t, e in bad.items())
        print(f"{p['name']} {p['version']}  types: {', '.join(p['types'])}  {state}")
    dists = plugin_dists()
    have = {norm(d.metadata["Name"]) for d in dists}
    gone = [s for s in manifest if not any(norm(d.metadata["Name"]) in have and spec_matches(s, d.metadata["Name"], dists)
                                            for d in dists)]
    for s in gone:
        print(f"{s}  MISSING for Python {sys.version_info.major}.{sys.version_info.minor}")
    if gone:
        print("run `vice plugin install --reinstall` to rebuild it")
    if not pk and not gone:
        print("no plugins installed (vice plugin install <package>)")
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser("plugin", help="add third-party source packages that survive upgrades")
    ps = p.add_subparsers(dest="plugin_cmd", required=True, metavar="action")
    i = ps.add_parser("install", help="install packages (PyPI name, name==1.2, path or git URL)")
    i.add_argument("specs", nargs="*", metavar="spec")
    i.add_argument("--reinstall", action="store_true", help="rebuild this Python's folder from plugins.toml")
    i.set_defaults(fn=_guarded(cmd_install))
    r = ps.add_parser("remove", help="remove a package")
    r.add_argument("name")
    r.set_defaults(fn=_guarded(cmd_remove))
    ps.add_parser("list", help="list installed packages").set_defaults(fn=_guarded(cmd_list))


def _guarded(fn):
    def run(args) -> int:
        try:
            return fn(args)
        except PluginError as e:
            print(f"vice: {e}", file=sys.stderr)
            return 1
    return run

"""Launch the pinned official Node runtime without using the older SEA executable."""
import json
import os
from pathlib import Path
import subprocess
import sys

base = Path(__file__).resolve().parent
try:
    launch = json.loads((base / ".state" / "runtime-launch.json").read_text(encoding="utf-8-sig"))
    node = Path(launch["node_path"])
    pwsh = Path(launch["pwsh_path"])
    package = base / "node_modules" / "@deepseek-ai" / "dsh"
    installed = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
    expected = json.loads((base / "config.json").read_text(encoding="utf-8"))["runtime_version"]
    if installed != expected or not node.is_absolute() or not pwsh.is_absolute() or not node.is_file() or not pwsh.is_file():
        raise RuntimeError("Reviewed Node, PowerShell or DSH runtime is missing; no fallback permitted.")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(node.parent), str(pwsh.parent), env.get("PATH", "")))
    # Both probes and SDK sessions use the same pinned Node and proxy implementation.
    args = ([str(base / "network-check.mjs")] if sys.argv[1:] == ["--network-check"]
            else [str(package / "lib" / "bin.js"), *sys.argv[1:]])
    # Inherit JSON-RPC pipes directly; no stdout decoration and no intermediate file.
    raise SystemExit(subprocess.call([str(node), *args], env=env))
except Exception as exc:
    print("DSH launcher failed: " + str(exc), file=sys.stderr)
    raise SystemExit(2)

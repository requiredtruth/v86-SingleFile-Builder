"""Deterministic asset validation, caching, and single-HTML assembly."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import html
import json
from pathlib import Path
import shutil
import urllib.request

REQUIRED_ASSETS = ("libv86.js", "v86.wasm", "seabios.bin", "vgabios.bin", "os-image.bin")
MEDIA = {"cdrom", "hda", "fda", "bzimage"}
MARKER_START = "<!-- V86_SINGLEFILE_MANIFEST_START\n"
MARKER_END = "\nV86_SINGLEFILE_MANIFEST_END -->"


@dataclass(frozen=True)
class Asset:
    name: str
    path: Path
    sha256: str
    source: str
    license: str


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_json(value) -> str:
    """JSON safe inside an HTML script element."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def load_config(path: str | Path) -> dict:
    config_path = Path(path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    config["_base"] = str(config_path.parent)
    return config


def validate_config(config: dict) -> list[Asset]:
    if config.get("medium") not in MEDIA:
        raise ValueError("medium must be one of: bzimage, cdrom, fda, hda")
    memory = int(config.get("memory_mb", 0))
    vga = int(config.get("vga_memory_mb", 0))
    if not 16 <= memory <= 4096: raise ValueError("memory_mb must be between 16 and 4096")
    if not 1 <= vga <= 256: raise ValueError("vga_memory_mb must be between 1 and 256")
    entries = config.get("assets")
    if not isinstance(entries, dict): raise ValueError("assets must be an object")
    base = Path(config.get("_base", "."))
    assets: list[Asset] = []
    for name in REQUIRED_ASSETS:
        entry = entries.get(name)
        if not isinstance(entry, dict): raise ValueError(f"missing asset metadata: {name}")
        path = (base / str(entry.get("path", ""))).resolve()
        expected = str(entry.get("sha256", "")).lower()
        source = str(entry.get("source", "")).strip()
        license_name = str(entry.get("license", "")).strip()
        if not path.is_file(): raise ValueError(f"asset file not found: {name}")
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError(f"asset sha256 must be 64 lowercase hex characters: {name}")
        if not source: raise ValueError(f"asset source is required: {name}")
        if not license_name: raise ValueError(f"asset license is required: {name}")
        actual = digest(path)
        if actual != expected: raise ValueError(f"asset sha256 mismatch: {name}")
        assets.append(Asset(name, path, actual, source, license_name))
    return assets


def cache_assets(assets: list[Asset], cache_dir: str | Path) -> list[Asset]:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    cached = []
    for asset in assets:
        destination = root / asset.sha256
        if not destination.exists():
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(asset.path, temporary)
            if digest(temporary) != asset.sha256:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"cache verification failed: {asset.name}")
            temporary.replace(destination)
        elif digest(destination) != asset.sha256:
            raise RuntimeError(f"cached asset is corrupt: {asset.sha256}")
        cached.append(Asset(asset.name, destination, asset.sha256, asset.source, asset.license))
    return cached


def fetch_asset(url: str, expected_sha256: str, destination: str | Path, max_bytes: int = 512 * 1024 * 1024) -> Path:
    """Fetch one explicit HTTPS URL and publish only after hash validation."""
    if not url.startswith("https://"):
        raise ValueError("asset URL must use https://")
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise ValueError("expected SHA-256 must be 64 lowercase hex characters")
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "v86-singlefile-builder/0.1"})
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk: break
                total += len(chunk)
                if total > max_bytes: raise ValueError("asset exceeds configured maximum size")
                handle.write(chunk)
        if digest(temporary) != expected_sha256: raise ValueError("downloaded asset SHA-256 mismatch")
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return output


def build(config: dict, output: str | Path, cache_dir: str | Path | None = None) -> dict:
    assets = validate_config(config)
    if cache_dir is not None: assets = cache_assets(assets, cache_dir)
    packed = {asset.name: base64.b64encode(asset.path.read_bytes()).decode("ascii") for asset in assets}
    asset_meta = {asset.name: {"bytes": asset.path.stat().st_size, "sha256": asset.sha256, "source": asset.source, "license": asset.license} for asset in assets}
    profile = {
        "name": str(config.get("name", "v86 VM"))[:120],
        "medium": config["medium"],
        "memoryMB": int(config["memory_mb"]),
        "vgaMemoryMB": int(config["vga_memory_mb"]),
        "acpi": bool(config.get("acpi", False)),
        "cmdline": str(config.get("cmdline", ""))[:1000],
        "notes": str(config.get("notes", ""))[:1000],
    }
    manifest = {"format": "v86-singlefile-v1", "profile": profile, "assets": asset_meta}
    page = render(profile, packed, asset_meta, manifest)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(destination)
    validate_output(destination)
    return {"output": str(destination), "bytes": destination.stat().st_size, "sha256": digest(destination), "assets": asset_meta}


def extract_manifest(page: str) -> dict:
    start = page.find(MARKER_START)
    end = page.find(MARKER_END, start + len(MARKER_START))
    if start < 0 or end < 0: raise ValueError("single-file manifest marker is missing")
    return json.loads(page[start + len(MARKER_START) : end])


def validate_output(path: str | Path) -> dict:
    page = Path(path).read_text(encoding="utf-8")
    manifest = extract_manifest(page)
    if manifest.get("format") != "v86-singlefile-v1": raise ValueError("unsupported output format")
    for name in REQUIRED_ASSETS:
        marker = f'"{name}":"'
        if marker not in page: raise ValueError(f"embedded asset missing: {name}")
    if "https://" in page.split("<script>", 1)[-1]:
        raise ValueError("runtime script contains an external HTTPS dependency")
    return manifest


def render(profile: dict, packed: dict, asset_meta: dict, manifest: dict) -> str:
    title = html.escape(profile["name"])
    notes = html.escape(profile["notes"])
    manifest_json = json.dumps(manifest, sort_keys=True)
    manifest_json = manifest_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline' blob: 'wasm-unsafe-eval'; worker-src blob:; connect-src blob:;">
<title>v86 — {title}</title><style>
*{{box-sizing:border-box}}html,body{{height:100%;margin:0;background:#020617;color:#e2e8f0;font:14px system-ui,sans-serif;overflow:hidden}}.app{{height:100%;display:grid;grid-template-rows:auto 1fr}}.bar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px;background:#0f172a;border-bottom:1px solid #334155}}button,input{{background:#111827;color:#f8fafc;border:1px solid #475569;border-radius:8px;padding:8px}}button{{font-weight:700;cursor:pointer}}button.primary{{background:#0f766e}}#status{{margin-left:auto;color:#93c5fd}}.main{{min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:8px;padding:8px}}#screen_container{{min-height:0;background:#000;border:1px solid #334155;border-radius:10px;display:flex;align-items:center;justify-content:center;overflow:hidden}}#screen_container canvas{{max-width:100%;max-height:100%;image-rendering:pixelated}}#screen_container div{{font:14px monospace;white-space:pre;color:#e2e8f0}}.side{{min-height:0;display:grid;grid-template-rows:auto 1fr auto;gap:8px}}.panel{{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:10px;overflow:auto}}#serial{{white-space:pre-wrap;font:12px monospace;color:#bbf7d0;background:#020617}}.command{{display:flex;gap:6px}}.command input{{min-width:0;flex:1}}.hidden{{display:none}}@media(max-width:820px){{.main{{grid-template-columns:1fr}}.side{{display:none}}#status{{width:100%;margin:0}}}}
</style></head><body><div class="app"><div class="bar"><strong>v86: {title}</strong><button id="boot" class="primary">Boot</button><button id="pause">Pause</button><button id="reset">Reset</button><button id="save">Save state</button><button id="load">Load state</button><input id="state" class="hidden" type="file"><button id="mouse">Lock mouse</button><button id="full">Fullscreen</button><span id="status">Ready.</span></div><div class="main"><div id="screen_container"><div>Press Boot to start {title}.</div><canvas style="display:none"></canvas></div><div class="side"><div class="panel"><b>{title}</b><br>{profile['medium']} · {profile['memoryMB']} MB RAM<br>{notes}</div><div id="serial" class="panel"></div><div class="panel command"><input id="command" aria-label="Serial command" placeholder="Send command to serial console"><button id="send">Send</button></div></div></div></div>
{MARKER_START}{manifest_json}{MARKER_END}
<script>
'use strict';const PROFILE={safe_json(profile)};const PACKED_ASSETS={safe_json(packed)};let emulator=null,paused=false;const urls=Object.create(null);const $=id=>document.getElementById(id);const status=s=>$("status").textContent=s;
function blob(b64,type){{const chunks=[];for(let o=0;o<b64.length;o+=131072){{const raw=atob(b64.slice(o,o+131072)),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);chunks.push(bytes)}}return new Blob(chunks,{{type}})}}
function url(name,type){{if(!urls[name])urls[name]=URL.createObjectURL(blob(PACKED_ASSETS[name],type));return urls[name]}}
function script(){{return new Promise((ok,fail)=>{{if(window.V86||window.V86Starter)return ok();const s=document.createElement('script');s.src=url('libv86.js','text/javascript');s.onload=ok;s.onerror=()=>fail(Error('Could not load embedded libv86.js'));document.head.appendChild(s)}})}}
function config(){{const c={{wasm_path:url('v86.wasm','application/wasm'),bios:{{url:url('seabios.bin')}},vga_bios:{{url:url('vgabios.bin')}},screen_container:$("screen_container"),serial_container:$("serial"),memory_size:PROFILE.memoryMB*1048576,vga_memory_size:PROFILE.vgaMemoryMB*1048576,autostart:true,acpi:PROFILE.acpi}},image={{url:url('os-image.bin')}};if(PROFILE.medium==='bzimage'){{c.bzimage=image;c.cmdline=PROFILE.cmdline||'console=ttyS0 root=/dev/ram0 rw'}}else c[PROFILE.medium]=image;return c}}
async function boot(){{if(emulator)return;status('Loading embedded assets…');await script();const C=window.V86||window.V86Starter;if(!C)throw Error('v86 constructor missing');emulator=new C(config());$("boot").disabled=true;status('Running.')}}
function download(data,name){{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([data]));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}}
$("boot").onclick=()=>boot().catch(e=>status('Boot failed: '+e.message));$("pause").onclick=()=>{{if(!emulator)return;paused=!paused;(paused?emulator.stop():emulator.run());$("pause").textContent=paused?'Resume':'Pause';status(paused?'Paused.':'Running.')}};$("reset").onclick=()=>emulator&&(emulator.restart?emulator.restart():emulator.reset());
$("save").onclick=()=>{{if(!emulator||!emulator.save_state)return status('State API unavailable.');status('Saving…');let settled=false;const done=state=>{{if(settled)return;settled=true;download(state,'v86-state.bin');status('State saved.')}};const fail=e=>{{if(settled)return;settled=true;status('Save failed: '+(e.message||e))}};try{{const ret=emulator.save_state((e,s)=>e?fail(e):done(s));if(ret&&ret.then)ret.then(done).catch(fail)}}catch(e){{fail(e)}}}};$("load").onclick=()=>$("state").click();$("state").onchange=e=>{{const f=e.target.files[0];if(!f||!emulator)return;f.arrayBuffer().then(b=>emulator.restore_state(b)).then(()=>status('State restored.')).catch(e=>status('Restore failed: '+e.message));e.target.value=''}};
$("send").onclick=()=>{{if(!emulator||!emulator.serial0_send)return status('Serial API unavailable.');emulator.serial0_send($("command").value+'\\n');$("command").value=''}};$("command").onkeydown=e=>{{if(e.key==='Enter')$("send").click()}};$("mouse").onclick=()=>$("screen_container").requestPointerLock?.();$("full").onclick=()=>document.documentElement.requestFullscreen?.();
</script></body></html>'''

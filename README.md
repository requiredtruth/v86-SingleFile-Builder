# v86-SingleFile-Builder

Package a complete licensed v86 virtual machine into one ordinary HTML file: emulator JavaScript, WebAssembly runtime, BIOS, VGA BIOS, and a kernel/disk image. The result performs no runtime asset fetch and includes boot, pause/resume, reset, save/restore state, serial command, pointer-lock, and fullscreen controls.

This repository preserves the generic single-file browser-VM builder idea while remaining independent of any desktop or application platform.

## Verify

```bash
sh install.sh
```

Seven tests build and validate synthetic offline VM packages, check deterministic output and cache integrity, reject incorrect hashes or missing licenses, escape script-breaking profile content, and block non-HTTPS fetching.

## Build a VM

1. Obtain `libv86.js` and `v86.wasm` from the official [v86 releases](https://github.com/copy/v86/releases).
2. Obtain compatible BIOS/VGA BIOS files and an x86 OS image you are permitted to redistribute.
3. Copy `config.example.json` and replace every path, SHA-256 digest, source, and license.
4. Build and validate:

```bash
python3 -m v86_singlefile build my-vm.json dist/my-vm.html
python3 -m v86_singlefile validate dist/my-vm.html
```

The builder refuses missing files, incorrect digests, missing source/license metadata, unsupported media, or unreasonable memory settings. Assets are cached by SHA-256 and verified again when reused.

To fetch an explicitly chosen asset with a known digest:

```bash
python3 -m v86_singlefile fetch \
  https://example.org/licensed-image.iso \
  <64-character-lowercase-sha256> \
  assets/os-image.bin
```

Fetching accepts HTTPS only, enforces a size limit, validates before publishing, and does not guess license metadata.

## Supported boot media

- `bzimage` with an optional kernel command line
- `cdrom`
- `hda`
- `fda`

## Why this differs

The official [v86](https://github.com/copy/v86) project is the emulator and optimized x86-to-WASM runtime. This project is a deterministic distribution builder around it: it turns an explicitly licensed asset set into one auditable offline HTML artifact and records exact byte sizes, sources, licenses, and hashes inside the output.

## Limitations

- v86 itself determines guest compatibility and performance; 64-bit kernels are not supported by v86.
- Base64 increases embedded asset size by roughly one third before HTML overhead.
- Browsers may struggle with very large single HTML files; test target devices directly.
- Version 0.1 uses the public v86 JavaScript API but does not bundle v86 or any operating-system image.
- Checksums detect corruption; they do not prove that an image is trustworthy or properly licensed.
- Opening via `file://` depends on browser CSP/WASM behavior. A local static HTTP server is more reliable while still requiring no external network.

## Support

Public donation addresses and the confirmed-transaction request process are in [SUPPORT.md](SUPPORT.md). Confirm the asset and network before sending.

## License

Builder code is MIT licensed. Embedded assets retain their own licenses.



## Install and run

```sh
chmod +x install.sh run.sh
./install.sh
./run.sh --help
```


## Standard launcher

`./run.sh` is the normal entry point. It runs `./install.sh` automatically when setup is missing, then opens the PySide6 control panel with live output and actions for the demo, tests, repair, and stop. Use `./cli.sh` for CLI-only operation.

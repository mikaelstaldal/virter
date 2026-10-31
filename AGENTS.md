# Agent Development Guidelines

## Project overview
- This repo is a single executable Python script: `virter`.
- It manages QEMU-based VMs and cloud-init seed images.
- OS target is Ubuntu 26.04+ (see `README.md`).

## Working agreements
- Keep the script executable and preserve the `#!/usr/bin/env python3` shebang.
- Prefer small, direct changes; this is a CLI tool with minimal structure.
- Add comments only when logic is non-obvious.
- Use Python 3 standard library and avoid external dependencies.

## Environment and dependencies
- External tools: `qemu-system-x86_64`, `qemu-img`, `genisoimage`.
- The script expects KVM acceleration and uses `XDG_CACHE_HOME` for cache.
- Avoid running QEMU commands in CI-style steps unless explicitly requested.

## Running and testing
- Run automated tests with `./verify.sh`; external commands are mocked and no VM is started.
- For functional verification, run `./virter --help` and, if requested, the relevant subcommand
  (`prepare`, `update`, `run`).
- Do not execute VM runs without user approval because they are heavy and interactive.

## Code changes
- Keep argument parsing in `main()`; add new subcommands alongside existing ones.
- Use `Path` for filesystem work and `subprocess.run(..., check=True)` for external commands.
- Be careful with temporary files and cleanup; preserve `try/finally` patterns.

## Safety
- Avoid destructive operations or deleting user files unless explicitly instructed.
- Treat cache and image paths as potentially user-owned; confirm before altering behavior.

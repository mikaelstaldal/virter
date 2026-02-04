#!/usr/bin/env python3

import argparse
import getpass
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    parser_setup = subparsers.add_parser("setup", help="Setup base image")
    parser_setup.add_argument("-b", "--base-image", type=Path, help="Base image filename", required=True)
    parser_setup.set_defaults(func=setup)

    parser_run = subparsers.add_parser("run", help="Run an instance")
    parser_run.add_argument("-n", "--name", help="Name of the instance", default=f"instance-{int(time.time())}")
    parser_run.set_defaults(func=run)

    args = parser.parse_args()
    if hasattr(args, "func") and args.func:
        args.func(args)
    else:
        parser.print_help()


def setup(args):
    base_image = args.base_image
    if not base_image.is_file():
        print("Base image not found")
        raise SystemExit(1)

    name = "base"
    vm_uuid = str(uuid.uuid4())
    memory_mib = 1024
    disk_mib = 4096
    timezone = read_timezone()

    cache_dir = prepare_cache_dir()

    temp_dir = Path(tempfile.mkdtemp())
    try:
        write_text_file(
            temp_dir / "meta-data",
            [
                "#cloud-config",
                f"instance-id: {name}",
                f"local-hostname: {name}",
                "cloud-name: virter",
            ]
        )
        write_text_file(
            temp_dir / "network-config",
            [
                "#cloud-config",
                "{}",
            ]
        )
        write_text_file(
            temp_dir / "vendor-data",
            [
                "#cloud-config",
                "growpart:",
                "  mode: auto",
                "  devices: [/]",
                "  ignore_growroot_disabled: false",
                "manage_etc_hosts: true",
                f"timezone: {timezone}",
                "user:",
                f"  name: \"{getpass.getuser()}\"",
                f"  uid: \"{os.getuid()}\"",
                "  lock_passwd: False",
                "  plain_text_passwd: password",
                "  groups: [adm, cdrom, dip, lxd, sudo]",
                "  sudo: [\"ALL=(ALL) NOPASSWD:ALL\"]",
                "  shell: /bin/bash",
            ]
        )
        write_text_file(
            temp_dir / "user-data",
            [
                "#cloud-config",
                "{}"
            ]
        )

        subprocess.run([
            "genisoimage",
            "-output",
            f"{name}-seed.img",
            "-volid",
            "cidata",
            "-rational-rock",
            "-joliet",
            "meta-data",
            "network-config",
            "vendor-data",
            "user-data",
        ], cwd=(str(temp_dir)), check=True)

        shutil.copy(base_image, cache_dir / "base.img")
        subprocess.run(["qemu-img", "resize", str(cache_dir / "base.img"), f"{disk_mib}M"], cwd=None, check=True)

        subprocess.run([
            "qemu-system-x86_64",
            "-name",
            name,
            "-uuid",
            vm_uuid,
            "-pidfile",
            f"{name}.pid",
            "-cpu",
            "host",
            "-accel",
            "kvm",
            "-m",
            str(memory_mib),
            "-nic",
            f"user,hostname={name}",
            "-drive",
            f"file={cache_dir / 'base.img'},index=0,format=qcow2,media=disk",
            "-drive",
            f"file={temp_dir}/{name}-seed.img,index=1,media=cdrom",
            "-qmp",
            "null",
            "-chardev",
            "stdio,id=stdio,signal=off",
            "-serial",
            "chardev:stdio",
            "-nographic",
        ], cwd=None, check=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run(args):
    name = args.name

    vm_uuid = str(uuid.uuid4())
    memory_mib = 1024
    timezone = read_timezone()

    cache_dir = prepare_cache_dir()

    temp_dir = Path(tempfile.mkdtemp())
    try:
        write_text_file(
            temp_dir / "meta-data",
            [
                "#cloud-config",
                f"instance-id: {name}",
                f"local-hostname: {name}",
                "cloud-name: virter",
            ]
        )
        write_text_file(
            temp_dir / "network-config",
            [
                "#cloud-config",
                "{}",
            ]
        )
        write_text_file(
            temp_dir / "vendor-data",
            [
                "#cloud-config",
                "growpart:",
                "  mode: auto",
                "  devices: [/]",
                "  ignore_growroot_disabled: false",
                "manage_etc_hosts: true",
                f"timezone: {timezone}",
                "users: []",
            ]
        )
        write_text_file(
            temp_dir / "user-data",
            [
                "#cloud-config",
                "{}",
            ]
        )

        subprocess.run([
            "genisoimage",
            "-output",
            f"{name}-seed.img",
            "-volid",
            "cidata",
            "-rational-rock",
            "-joliet",
            "meta-data",
            "network-config",
            "vendor-data",
            "user-data",
        ], cwd=(str(temp_dir)), check=True)

        subprocess.run([
            "qemu-img",
            "create",
            "-f",
            "qcow2",
            "-b",
            str(cache_dir / "base.img"),
            "-F",
            "qcow2",
            f"{name}.img",
        ], cwd=None, check=True)

        subprocess.run([
            "qemu-system-x86_64",
            "-name",
            name,
            "-uuid",
            vm_uuid,
            "-pidfile",
            f"{name}.pid",
            "-cpu",
            "host",
            "-accel",
            "kvm",
            "-m",
            str(memory_mib),
            "-nic",
            f"user,hostname={name}",
            "-drive",
            f"file={name}.img,index=0,format=qcow2,media=disk",
            "-drive",
            f"file={temp_dir}/{name}-seed.img,index=1,media=cdrom",
            "-qmp",
            "null",
            "-chardev",
            "stdio,id=stdio,signal=off",
            "-serial",
            "chardev:stdio",
            "-nographic",
        ], cwd=None, check=True)
    finally:
        img_path = Path(f"{name}.img")
        if img_path.exists():
            img_path.unlink()
        shutil.rmtree(temp_dir, ignore_errors=True)


def read_timezone():
    try:
        return Path("/etc/timezone").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def prepare_cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    cache_dir = Path(cache_home) / "virter"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def write_text_file(file: Path, lines: list[str]):
    file.write_text("\n".join(lines + [""]), encoding="utf-8")


if __name__ == "__main__":
    main()

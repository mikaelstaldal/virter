# virter

## Prerequisites

- Ubuntu 26.04 or later

```bash
sudo apt install python3 qemu-system-x86 qemu-utils genisoimage virtiofsd bubblewrap
```

## Host confinement

Run virter as an ordinary user with access to `/dev/kvm`; root execution is refused.
Every QEMU launch requires Bubblewrap and working unprivileged user namespaces. Failure to create the sandbox
aborts the launch; there is no unconfined fallback. Ubuntu's AppArmor policy must permit the packaged `bwrap`
to create user namespaces.

QEMU runs with separate user, mount, PID, IPC and UTS namespaces, no capabilities, a cleared environment,
and explicit seccomp restrictions. Its filesystem contains read-only system runtime files, a private `/tmp`
and `/dev/shm`, `/dev/kvm`, the instance directory and the required disk images. Ephemeral instances see their
base image read-only; `prepare` and `update` can write their selected base image. Other cache images and the
user's home are not exposed. Host networking is retained only with `--network host` (also used for image updates).
This exposes host loopback services and abstract Unix sockets to QEMU. Runs default to `--network none`,
which disables the guest NIC and isolates QEMU in a separate network namespace.
A non-VM confinement preflight checks namespace creation and KVM device visibility before modifying images.
The host QEMU process cannot create additional user namespaces inside its Bubblewrap sandbox.
This does not restrict user namespaces or containers inside the VM, which runs its own kernel.

Directory sharing uses a separate virtiofsd process running as the invoking user, outside this QEMU sandbox.
Mounts of your home directory or any ancestor (such as `/` or `/home`) are refused in both read-only and
writable mode, including with `--current-dir` and `--current-dir-writable`. Symlink aliases are resolved first.
Overlapping shared directories must use the same access mode; mixing read-only and writable exports is rejected
because a writable parent export would bypass a read-only child export.

A shared directory deliberately grants the guest access to its contents according to the requested mount mode.
Confinement is defense in depth and does not protect against host kernel vulnerabilities.

## Prepare image automatically

Only trusted, authenticated, standalone QCOW2 images are supported. A checksum computed from an untrusted image
is not authentication. Virter does not provide a sandboxed importer for arbitrary images; image metadata is parsed
by host QEMU tools. Backing files and external data files are refused before QEMU is invoked.

For Ubuntu, download the image and signed checksum manifest from
[Ubuntu Cloud Images](https://cloud-images.ubuntu.com/resolute/current/).
Install the Ubuntu cloud image signing keyring from the authenticated Ubuntu package archive:

```bash
sudo apt install ubuntu-cloudimage-keyring curl
BASE_IMAGE=resolute-server-cloudimg-amd64.img
IMAGE_URL=https://cloud-images.ubuntu.com/resolute/current
curl --fail --remote-name "$IMAGE_URL/$BASE_IMAGE"
curl --fail --remote-name "$IMAGE_URL/SHA256SUMS"
curl --fail --remote-name "$IMAGE_URL/SHA256SUMS.gpg"
gpgv --keyring /usr/share/keyrings/ubuntu-cloudimage-keyring.gpg SHA256SUMS.gpg SHA256SUMS
```

Continue only if signature verification succeeds. Extract the exact image's checksum from the verified manifest
and pass it to virter, which checks the copied bytes before opening the image with QEMU:

```bash
IMAGE_SHA256=$(awk -v image="$BASE_IMAGE" '$2 == image || $2 == "*" image {print $1}' SHA256SUMS)
./virter prepare -i "$BASE_IMAGE" --sha256 "$IMAGE_SHA256"
```

If verification fails, stop and download a matching image and manifest; do not substitute a locally computed checksum.
Keep the verified manifest unchanged until the digest has been extracted.

Base and instance names (`--base` and `--name`) must contain 1–63 ASCII letters, digits or hyphens,
starting and ending with a letter or digit. Preparing an existing base is refused; choose a new base name
or use `update` to modify it. Base images must not be symlinks.

## Update an image interactively

```bash
./virter update
```

Any changes to the file system will be persisted.

## Run an ephemeral instance

Changes to the instance disk are discarded when the instance exits. Writes to writable host shares persist
on the host, including when the VM fails; deleting the instance disk does not undo them.

Runs are offline by default (`--network none`). To explicitly enable networking:

```bash
./virter run --network host
```

Despite its name, `host` uses QEMU user-mode networking (NAT), not a bridged guest interface.
It permits unrestricted outbound access to the internet, LAN and host services, including host loopback
services via the guest-visible host address (normally `10.0.2.2`). NAT does not provide an outbound security
boundary. Virter does not offer an internet-only mode or filter private, link-local, IPv4 or IPv6 destinations;
use offline mode for untrusted guests. Image preparation and updates also use this unrestricted networking.

The guest inherits the invoking user's `LANG`, `LANGUAGE`, and nonempty `LC_*` locale settings on each
`prepare`, `update`, and `run`. Requested locales are generated only during `prepare` and `update`,
so run `update` with new locale settings before using them with `run`. When `LANG` is unset, `C.UTF-8` is used.
Language translations depend on the packages installed in the image.
The timezone follows `TZ` when set, otherwise the host system timezone. POSIX `TZ` rules are passed to
the guest shell even when they cannot be used as a system timezone.

### With an interactive shell

```bash
./virter run
```

### With a command and then exit

```bash
./virter run -- ls -A /
```

Both stdout and stderr from the instance will end up in stdout from the virter command.

### With a directory on the host mounted writable

`--mount-writable` and `--current-dir-writable` give the guest persistent write authority over the shared
host directory. A guest can alter source code, executables, build configuration or shell startup files that
later execute on the host. QEMU confinement does not prevent these authorized writes through virtiofsd.
Writable mounts overlapping the virter cache (normally `$XDG_CACHE_HOME/virter`,
or `~/.cache/virter`) are also refused, protecting base images and other instances. Paths are resolved before
these checks, including symlink aliases. Other directories inside your home can still be shared writable;
avoid sharing credentials or an active checkout.

```bash
./virter run --mount-writable DIR
./virter run --current-dir-writable
```

For untrusted guest work, prefer read-only inputs and a dedicated, disposable staging directory for output.
If the guest needs to modify inputs, copy only the required files into staging first. For example:
Run this from the input directory, with the temporary directory location outside that directory so the
read-only input and writable staging exports do not overlap. Set `TMPDIR` to a separate location if needed.

```bash
staging=$(mktemp -d)
./virter run --mount "$PWD" --mount-writable "$staging"
```

The staging directory appears at the same absolute path inside the guest. After the VM exits, treat everything
in it as untrusted: inspect changes and check file types and symlink targets before manually copying selected
results to a separate destination. Do not execute generated scripts, source configuration, or run builds from
staging as part of review. There is no automatic result export or trust validation. Remove staging manually
when finished; its contents persist until you do.

### With a directory on the host mounted read-only

```bash
./virter run --mount DIR
./virter run --current-dir
```

### With several directories on the host mounted

`--mount` and `--mount-writable` can be repeated and combined with each other and with one of the current directory
options. Each directory appears at the same path inside the instance as on the host.

```bash
./virter run --mount DIR1 --mount DIR2 --mount-writable DIR3 --current-dir-writable
```
    
## Testing

Run the automated tests with Python 3; external commands are mocked and no VM is started.

```bash
./verify.sh
```

## License

Copyright 2026 Mikael Ståldal.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

# virter

## Prerequisites

- Ubuntu 26.04 or later

```bash
sudo apt install python3 qemu-system-x86 qemu-utils genisoimage virtiofsd
```

## Prepare image automatically

Fetch https://cloud-images.ubuntu.com/resolute/current/resolute-server-cloudimg-amd64.img

```bash
./virter prepare -i $BASE_IMAGE
```

Base and instance names (`--base` and `--name`) must contain 1–63 ASCII letters, digits or hyphens,
starting and ending with a letter or digit. Preparing an existing base is refused; choose a new base name
or use `update` to modify it. Base images must not be symlinks.

## Update an image interactively

```bash
./virter update
```

Any changes to the file system will be persisted.

## Run an ephemeral instance

Any changes to the file system will be discarded when the instance exits.

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

```bash
./virter run --mount-writable DIR
./virter run --current-dir-writable
```

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

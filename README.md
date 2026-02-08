# virter

## Prerequisites

- Ubuntu 24.04 or later

```bash
sudo apt install python3 qemu-system-x86 qemu-utils genisoimage virtiofsd
```

## Prepare image automatically

Fetch https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

```bash
./virter prepare -i $BASE_IMAGE
```

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

**Note:** This requires a newer version of `virtiofsd` than the one in Ubuntu 24.04. 
    
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

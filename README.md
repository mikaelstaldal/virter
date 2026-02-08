# virter

## Prerequisites

- Ubuntu 24.04 or later

```bash
sudo apt install python3 qemu-system-x86 qemu-utils genisoimage virtiofsd
```

## Prepare image

Fetch https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

Run `./virter prepare -i $BASE_IMAGE`

## Run an instance with an interactive shell

Run `./virter run`

## Run an instance with a command and then exit

Run `./virter run -- ls -A /`

Both stdout and stderr from the instance will end up in stdout from the virter command.
    
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

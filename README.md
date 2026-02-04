# virter

## Prerequisites

- Ubuntu 24.04 or later

```bash
sudo apt install python3 qemu-system-x86 qemu-utils genisoimage
```

## Setup image

Fetch https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

Run `./virter setup -b $BASE_IMAGE` and do this:

1. Login with your username and password `password`
2. sudo nano /boot/grub/grub.cfg

    linux   /vmlinuz-6.8.0-90-generic root=LABEL=cloudimg-rootfs ro quiet console=ttyS0 systemd.getty_auto=no

3. sudo systemctl disable ssh
4. sudo systemctl disable ssh.socket
5. sudo systemctl disable getty@tty1.service
6. sudo nano /usr/lib/systemd/system/serial-getty@.service 
   
    ExecStart=-/sbin/agetty --noissue --noclear -a <your_username> -o '-p -f -- \\u' --keep-baud 115200,57600,38400,9600 - $TERM
    ExecStart=/sbin/shutdown -h --no-wall now
    Type=oneshot
    Restart=no
    TTYColumns=120 # desired terminal size
    TTYRows=50     # desired terminal size

7. sudo systemctl disable serial-getty@ttyS0.service
8. sudo systemctl enable serial-getty@ttyS1.service 
9. sudo passwd -d <your_username> 
10. sudo shutdown -h --no-wall now

## Run an instance

Run `./virter run`
    
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

# virter

## Setup image

Fetch https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

Run `./virter setup -b $BASE_IMAGE` and do this:

1. Login with your username and password `password` 
2. sudo systemctl disable ssh
3. sudo systemctl disable ssh.socket
4. sudo systemctl disable getty@tty1.service
5. sudo nano /usr/lib/systemd/system/serial-getty@.service 
   
    ExecStart=-/sbin/agetty -a <your_username> -o '-p -f -- \\u' --keep-baud 115200,57600,38400,9600 - $TERM
    ExecStart=/sbin/shutdown -h --no-wall now
    Type=oneshot
    Restart=no
    
6. sudo shutdown -h --no-wall now

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

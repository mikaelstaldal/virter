#!/bin/bash

if [ "$1" == "" ]; then
  echo "Please specify base image"
  exit 1
fi
BASE_IMAGE=$1
if [ ! -f "$BASE_IMAGE" ]; then
  echo "Base image not found"
  exit 1
fi

NAME=base
UUID=$(uuid)
MEMORY_MIB=1024
TIMEZONE=$(cat /etc/timezone)

CACHE_HOME=${XDG_CACHE_HOME-${HOME}/.cache}
CACHE_DIR="$CACHE_HOME/virter"
mkdir -p "$CACHE_DIR"

TEMP_DIR=$(mktemp -d)

cat <<EOF >"${TEMP_DIR}/meta-data"
#cloud-config
instance-id: ${NAME}
local-hostname: ${NAME}
cloud-name: virter
EOF

cat <<EOF >"${TEMP_DIR}/network-config"
#cloud-config
{}
EOF

cat <<EOF >"${TEMP_DIR}/vendor-data"
#cloud-config
growpart:
  mode: auto
  devices: [/]
  ignore_growroot_disabled: false
manage_etc_hosts: true
timezone: ${TIMEZONE}
user:
  name: "$(id -un)"
  uid: "$(id -u)"
  lock_passwd: False
  plain_text_passwd: password
  groups: [adm, cdrom, dip, lxd, sudo]
  sudo: ["ALL=(ALL) NOPASSWD:ALL"]
  shell: /bin/bash
EOF

cat <<EOF >"${TEMP_DIR}/user-data"
#cloud-config
{}
EOF

(cd "$TEMP_DIR" && genisoimage -output "${NAME}-seed.img" -volid cidata -rational-rock -joliet meta-data network-config vendor-data user-data)

cp "$BASE_IMAGE" "$CACHE_DIR/base.img"

qemu-system-x86_64 \
  -name "$NAME" -uuid "$UUID" -pidfile "${NAME}.pid" \
  -cpu host -accel kvm -m "$MEMORY_MIB" \
  -nic "user,hostname=$NAME" \
  -drive "file=${CACHE_DIR}/base.img,index=0,format=qcow2,media=disk" \
  -drive "file=${TEMP_DIR}/${NAME}-seed.img,index=1,media=cdrom" \
  -qmp null -chardev stdio,id=stdio,signal=off -serial chardev:stdio -nographic

rm -rf "$TEMP_DIR"

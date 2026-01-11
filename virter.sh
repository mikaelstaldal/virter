#!/bin/bash

NAME=${1:-$(date +instance-%s)}
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
users: []
EOF

cat <<EOF >"${TEMP_DIR}/user-data"
#cloud-config
{}
EOF

(cd "${TEMP_DIR}" && genisoimage -output "${NAME}-seed.img" -volid cidata -rational-rock -joliet meta-data network-config vendor-data user-data)

qemu-img create -f qcow2 -b "$CACHE_DIR/base.img" -F qcow2 "${NAME}.img"

qemu-system-x86_64 \
  -name "$NAME" -uuid "$UUID" -pidfile "${NAME}.pid" \
  -cpu host -accel kvm -m "$MEMORY_MIB" \
  -nic "user,hostname=$NAME" \
  -drive "file=${NAME}.img,index=0,format=qcow2,media=disk" \
  -drive "file=${TEMP_DIR}/${NAME}-seed.img,index=1,media=cdrom" \
  -qmp null -chardev stdio,id=stdio,signal=off -serial chardev:stdio -nographic

rm "${NAME}.img"
rm -rf "$TEMP_DIR"

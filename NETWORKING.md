# Bridge networking

`./virter run --network bridge` permits outbound TCP, UDP and ping to Internet and LAN peers while
blocking services on the host. The default remains `none`. The CLI name describes LAN reachability;
the backend is passt socket translation, **not** an Ethernet bridge. Guests cannot emit arbitrary Ethernet
frames on the LAN. `host` remains unrestricted QEMU user networking and needs none of the setup below.

Running virter needs no sudo. An administrator installs the host setup once; after that, members of the
`virter-bridge` group can start bridge VMs.

## Boundary and prerequisites

Passt's `--no-map-gw` and disabled host mappings alone are insufficient: a guest could still contact another
host address. This mode instead requires a dedicated `virter-passt` account and the exact nftables policy in
[network/virter-bridge.nft](network/virter-bridge.nft). An early output hook drops destinations whose
live route type is `local`, before normal output DNAT can turn a host-published port into a container address.
A later output hook marks **every** remaining packet from this account. The host input hook drops that mark
before socket delivery, including traffic redirected to a host socket after the early check. The `inet` family
applies to both IPv4 and IPv6, independent of port, destination address, interface, local route or address changes.
Loopback, wildcard listeners, host LAN/global/link-local addresses, IPv4-mapped IPv6 destinations and local
DNAT/REDIRECT targets therefore receive no guest traffic. No address snapshot or DNS-name filtering is used.

The mark `0x76527472` is reserved for this policy. An administrator must ensure that no other firewall,
packet marking, tunnel, routing, tc or BPF policy clears or changes it between the output and input hooks,
or bypasses these hooks. Output DNAT must run after the early hook at priority -450. The service atomically
replaces the table with this exact policy before every passt start, so no boot-time firewall setup is needed and
an altered table does not survive the next VM launch. Never flush the firewall while bridge VMs are active: virter
cannot defend against an administrator changing policy after passt has started. Existing firewall rules may further
restrict Internet/LAN connectivity. No host forwarding, masquerade or bridge device is needed.

Use this mode only on a host whose network path satisfies these prerequisites. Remote proxies, VPN gateways,
routers with NAT hairpinning, and LAN services that relay requests back to the host are outside the direct
host-service boundary. Do not provide such relays to an untrusted guest. Traffic that leaves the host and
returns as a new unmarked packet cannot be identified by this policy. Direct container/VM peer addresses on local
bridges are also reachable: they are not addresses assigned to the host itself. Such peers must not relay requests
to host services. Host-published ports addressed through a host IP are blocked by the early route-type check,
including publication through output DNAT.
This mode does not make the LAN safe from an untrusted guest, provide traffic quotas, or protect against kernel or
passt vulnerabilities.

QEMU retains its separate network namespace, filesystem confinement and seccomp restrictions. Its only
network connection is one inherited, already connected Unix stream socket. Virter connects to
`/run/virter-passt.sock`, where systemd starts one passt instance per connection, and hands that socket to QEMU.
Passt runs outside QEMU's sandbox and virter's systemd scope, under the dedicated UID with arguments fixed by the
administrator-owned unit. It uses its own built-in sandbox and forwards no inbound TCP or UDP ports. Keep this UID
exclusively for passt, with no login, credentials, file ownership beyond necessary runtime state, or other workloads.

The backend requires packaged passt with `--fd`, `--map-host-loopback`, `--map-guest-addr`, `--dns-host` and
`--dns-forward`, QEMU 7.2 or newer, systemd, and nftables 1.0.8 or newer with Linux 6.3 or newer (`destroy table`,
`inet` input/output hooks and `meta skuid`).

A missing socket or missing group membership aborts the run before anything starts. There is no fallback to `host`.
Systemd accepts the connection before it starts the service, so virter cannot see a later failure of nft or passt.
The guest then boots with no working network, and the same applies if passt exits during a run. Find the cause with
`journalctl -u 'virter-passt@*'`. Passt exits when QEMU closes the socket.

## Administrator setup

These are deliberate host configuration changes. Review them for the host's firewall policy;
virter never installs accounts, units or firewall rules itself.

```bash
sudo apt install passt nftables
sudo useradd --system --no-create-home --shell /usr/sbin/nologin virter-passt
sudo groupadd --system virter-bridge
sudo install -D -m 0644 network/virter-bridge.nft /usr/local/share/virter/virter-bridge.nft
sudo install -m 0644 network/virter-passt.socket network/virter-passt@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now virter-passt.socket
sudo usermod -aG virter-bridge alice
```

Replace `alice` with each permitted user, who must log in again for the group to take effect. If the account already
exists, verify it is dedicated and unprivileged instead of recreating it. Do not change its UID while VMs run.
The nftables file only ever replaces its own `virter_bridge` table, and it is loaded as root, so keep it root-owned.
Removing a user from the group takes effect only once their existing login sessions end, and it does not stop VMs
already running.

Passt runs under its packaged AppArmor profile, which applies automatically. Do not add `AppArmorProfile=` to the
unit: AppArmor stacks that profile on the packaged one, and passt is then killed with SIGSEGV when it re-executes
its AVX2 build.

Group members can only start passt with the fixed arguments in the unit. The unit limits each instance's memory,
tasks and CPU, and the socket limits the host to 16 concurrent instances. Adjust these in a drop-in if needed.

## DNS and infrastructure

Passt supplies ARP, DHCP, IPv6 NDP/router advertisements and DHCPv6 internally on the guest link. These
are protocol-specific configuration services, not exceptions allowing guest connections to host sockets.
Host/gateway and guest-address mappings are disabled. No host resolver or search domain is inherited:
DHCP advertises Cloudflare's public `1.1.1.1`, and explicit DNS forwarding for `1.1.1.1` and
`2606:4700:4700::1111` targets only those same public resolvers (ports 53 and 853). Queries therefore leave
the host under the filtered UID. This sends DNS queries to Cloudflare; private split DNS is not supported.
A host-local DNS listener has no exemption, even on port 53. If public DNS is blocked, use numeric peer
addresses for diagnostics; virter does not fall back to the host resolver. IPv6 outbound access requires a
working host IPv6 route; absence of that route does not enable an alternate host-access path.

The implementation follows the [passt manual](https://passt.top/builds/latest/web/passt.1.html) and
[QEMU stream backend documentation](https://www.qemu.org/docs/master/system/qemu-manpage.html).
The [netfilter hook ordering](https://wiki.nftables.org/wiki-nftables/index.php/Netfilter_hooks) explains
the pre-NAT route check and the final input drop.

## Integration verification (operator run)

Automated tests mock external tools. The following checks require a prepared trusted base, administrator
setup above, reachable services on a **different** LAN machine, and explicit approval to start VMs.
Run them on a disposable test host before using the mode for untrusted code. Record commands and results.

[network/verify-bridge](network/verify-bridge) automates most of them. It starts VMs, but never changes host
configuration: it prints any administrator commands for you to run in another terminal, then checks the outcome.

```bash
# On a different LAN machine; repeat the host's --peer for IPv6 as [ADDRESS]:PORT
python3 verify-bridge peer --port 18900

# On the test host: preflight and steps 1-5 and 7
./network/verify-bridge run --peer LAN_ADDRESS:18900 --must-block HOST_IP:PUBLISHED_PORT

# On the test host: the failure cases in step 6, one by one
./network/verify-bridge failures
```

Each run writes `report.json` and VM logs to a new directory, and exits non-zero if any check failed. `MANUAL` lines
are for you to confirm. `--help` lists the other options. The steps below describe what is checked.

1. Inventory every host IPv4/IPv6 address with `ip -br address`, including secondary addresses and interfaces.
   Choose a LAN peer and an Internet HTTPS endpoint; confirm both are reachable directly from the host.
   Include an IPv6 LAN/Internet peer where the host supports IPv6.
2. On the host, start TCP HTTP test listeners on separate ports bound to `127.0.0.1`, `::1`, `0.0.0.0`, `::`,
   and each host LAN/global address. For example, run `python3 -m http.server 18080 --bind 127.0.0.1` in
   a terminal, varying port and bind address for each listener. Confirm listeners work from the host.
   Also start a UDP echo listener on loopback, wildcard and LAN addresses using an approved local test tool,
   including a DNS test listener on port 53 if available. Start known TCP and UDP services on the LAN peer.
3. Run `./virter run --network bridge` interactively. From the guest, inspect `ip address`, `ip route`,
   `ip -6 route` and `resolvectl status`. Resolve a public name and fetch the Internet HTTPS endpoint and
   LAN HTTP service using `curl --connect-timeout 3`. Verify TCP and UDP reach the peer in both available
   address families. Lack of IPv6 routing should produce failure, never host-service access.
4. From the guest, try every host test port against every inventoried host address, the advertised gateway,
   the guest's assigned address, `10.0.2.2`, `10.0.2.3`, `127.0.0.1`, `127.0.0.2`, `::1`, and IPv4-mapped
   IPv6 forms such as `::ffff:HOST_IPV4`. Use `curl --noproxy '*' --connect-timeout 3` and a UDP test client.
   Link-local IPv6 targets need the guest interface scope (for example `%enp0s2`). Every host service must
   be unreachable, including host DNS over UDP/TCP 53. Verify host listeners receive no requests.
   Guest loopback may reach guest services; the assertion concerns the host listeners.
   Passt gives the guest the host's own address, so probes to that address stay inside the guest. Repeat with the
   guest moved to a different address and default route, which is what a malicious guest could do.
5. While the guest runs, add a secondary IPv4 and IPv6 host address in the test network using the host's
   normal network tools, bind test listeners to them and repeat step 4. No policy reload should be needed.
   If the deployment uses local DNAT/REDIRECT, exercise those aliases too; none may deliver to host listeners.
   Also test a host-published Docker/LXD/libvirt port forwarded to a container or VM: connecting via a host
   IP must fail. Direct container/VM addresses may work, as documented; verify these peers cannot relay back
   to host services before considering the deployment isolated.
   Verify no other policy changes the reserved mark. Remove only the addresses/listeners created for this test.
6. Exit the guest. On the disposable host, test each failure, one at a time. Without the socket unit, or for a user
   outside the group, a bridge run must abort without an unrestricted QEMU network. With an invalid nftables file,
   the guest must boot without working network and `journalctl -u 'virter-passt@*'` must show the failure. With an
   altered or extra rule in the table, the next bridge run must restore the exact policy (`nft list table inet
   virter_bridge`). Restore the administrator setup after each case. Never remove the table while a VM is active.
   Terminate passt during a run: the guest must lose networking without switching backend. Confirm no
   `virter-passt@` instance remains after normal exit or cancellation.
7. Run the default `./virter run` and confirm no guest NIC/network is available. On this controlled test host,
   explicitly run `--network host` and confirm the host test listener is reachable via `10.0.2.2`, establishing
   that the blocked bridge checks tested real listeners. Stop all test listeners when finished.

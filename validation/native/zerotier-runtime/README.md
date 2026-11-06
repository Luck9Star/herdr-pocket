# ZeroTier device and network control plane

This candidate calls the pinned patched libzt API. One process-global device
owner holds the durable Android vault runtime lease; each profile gets a separate
network lease. It never creates an identity, chooses a storage path, imports an
environment key, starts a second node, or falls back to a system socket.

`hp_zt_device_new` accepts only the already persisted, strictly validated private
identity. It reserves an owner before touching native initialization, initializes
from memory and disables identity/network/peer/root caches. Caller buffers remain
borrowed until the original call returns. No raw private bytes cross a GUI channel.
The host must keep this library loaded and route all libzt control through the
manager; mixing raw node APIs with this owner is unsupported. A preexisting
foreign raw node is refused and is not stopped during cleanup of the refused owner.

`device_start` requests one start. `STARTED` means only that the synchronous start
API returned, not that the asynchronously created node is online. An explicit
network join requires online status and the exact expected public node ID. Each
join has a monotonic, non-reusable lease; repeated profiles for one network share
the actual join, while leaving one lease does not disturb its remaining profiles.
The last lease for network A leaves A only. It never stops network B or releases
the device identity. At most 32 network leases include failed and pending cleanup.

Native configuration status maps requesting, configured, denied, missing network,
port error, obsolete client and authentication required separately. Configured is
not route readiness. No socket API is exposed yet: exact family/tap generation,
route binding, cancellation and per-stream drain must be implemented before
connecting a ZeroTier terminal. An asynchronous startup failure currently remains
offline; it is not yet distinguished from a node still starting.

`device_stop` is an explicit device-wide action that fences all admissions. The
host must first review all affected profiles. Stop waits for the original control
call, requests native retirement and requires quiescence; timeout/error retains
the owner, networks and vault. `device_release` accepts only that exact stopped
owner, with no retained networks and native quiescence. Repeated or foreign
release returns stale, so the host must retain its successful original result for
the vault's exact `handle/instance/lease` retirement proof. A `NODE_DOWN` event or
one network leaving cannot produce that proof. Permanent native `free` is unused.

The timeout bounds control admission and the native stop operation. Upstream
init/join/status calls cannot be preempted: a late call returns timeout with its
original owner retained, and no buffer or vault lease may be released while it
is still executing. Start or join is never automatically replayed. A failed join
can return a nonzero lease; explicit leave or device-wide stop must clean it up.

The actual manager is tested against the fixed real libzt header with synthetic
engine symbols, including blocked calls, old owners, same-network refcounts,
cross-network leave isolation, capacity and failed cleanup. These tests do not
start a node or prove a real network, Android KeyStore or JNI integration:

```sh
python3 validation/native/zerotier-runtime/tests/run_manager.py \
  /absolute/prepared-candidate/libzt --output /absolute/new-output
```

Two independently reproduced regressions are retained in the validation record:
stop during the online query must prevent the later join side effect, and an
expired quiescence query must not begin identity initialization. Checks after
those original queries now enforce the fence and deadline.

Current documentation was resolved with Context7 `library` then `docs` for
ZeroTier, using the official [Sockets guide](https://github.com/zerotier/docs/blob/main/docs/sockets.md).
Its examples are background only; actual calls, error codes and status mapping
were checked against the fixed Heeler/libzt/ZeroTierOne commits in
[`zerotier-runtime-source.json`](../zerotier-runtime-source.json). In particular,
the guide's assigned-address readiness example is not used as dial permission.

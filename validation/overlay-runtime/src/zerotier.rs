//! One native device shared by per-profile network reservations. No private
//! identity, plaintext store, system socket or DNS fallback exists here.
use crate::nodes::{NodeSpec, NodeStatus};
use crate::{Backend, Evidence, Failure, Provider, Result};
use std::sync::{Arc, atomic::AtomicBool};
use std::time::Duration;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NetworkPhase {
    Requesting,
    Configured,
    Denied,
    NotFound,
    PortError,
    ClientOld,
    AuthRequired,
    Unknown,
}

/// Native host custody. acquire must preserve an exact, non-reusable reservation
/// before device creation. Once any owner may exist, return a config carrying
/// startup_failure, not an Err that loses the cleanup reference. A failed/no-owner
/// reservation is still explicitly retired; owner==0 is never a drain proof.
pub trait NativeDeviceSource: Send + Sync + 'static {
    fn acquire(&self, spec: &NodeSpec, deadline: Duration) -> Result<NativeDeviceConfig>;
}
/// One reservation for the original profile attempt, backed by the process-wide
/// device owner. Different reservations may share the same owner. Drop MUST NOT
/// release custody: only retire_after_network may do so, after original calls and
/// this reservation's network/streams have drained. The final reservation must
/// prove native stop+release before unlocking the durable device vault.
pub trait NativeDeviceSession: Send + Sync + 'static {
    fn identity_ref(&self) -> &str;
    fn owner(&self) -> u64;
    fn retire_after_network(&self, deadline: Duration) -> Result<()>;
}
/// No Debug/Clone/serde: this carries native custody, not GUI metadata.
#[cfg_attr(not(feature = "linked-zerotier"), allow(dead_code))]
pub struct NativeDeviceConfig {
    spec: NodeSpec,
    session: Arc<dyn NativeDeviceSession>,
    startup_failure: Option<Failure>,
}
impl NativeDeviceConfig {
    pub fn for_spec(
        spec: &NodeSpec,
        session: Arc<dyn NativeDeviceSession>,
        startup_failure: Option<Failure>,
    ) -> Result<Self> {
        validate_spec(spec)?;
        if session.identity_ref() != spec.identity_ref
            || (session.owner() == 0 && startup_failure.is_none())
        {
            return Err(Failure::InvalidRoute);
        }
        Ok(Self {
            spec: spec.clone(),
            session,
            startup_failure,
        })
    }
}
/// Call this before a host source acquires any native custody.
pub fn validate_spec(spec: &NodeSpec) -> Result<()> {
    if spec.profile.provider != Provider::ZeroTier
        || spec.revision == 0
        || spec.profile_revision == 0
        || spec.profile.id.is_empty()
        || spec.profile.id.len() > 128
        || !spec
            .profile
            .id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        || spec.identity_ref.is_empty()
        || spec.identity_ref.len() > 256
        || spec.identity_ref.chars().any(char::is_control)
        || network_id(&spec.network).is_err()
    {
        return Err(Failure::InvalidRoute);
    }
    Ok(())
}
fn network_id(value: &str) -> Result<u64> {
    if value.len() != 16
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(Failure::InvalidRoute);
    }
    u64::from_str_radix(value, 16)
        .ok()
        .filter(|id| *id != 0)
        .ok_or(Failure::InvalidRoute)
}

#[cfg(feature = "linked-zerotier")]
mod linked {
    use super::*;
    use crate::{MAX_DEADLINE, MAX_IO, lock};
    use std::collections::HashSet;
    use std::net::IpAddr;
    use std::sync::{Mutex, atomic::Ordering};
    use std::time::Instant;

    pub(super) const OK: i32 = 0;
    const STALE: i32 = 2;
    const BUSY: i32 = 3;
    const TIMEOUT: i32 = 4;
    const CAPACITY: i32 = 6;
    const CLOSING: i32 = 9;
    const CANCELLED: i32 = 10;
    #[link(name = "hp_zerotier")]
    unsafe extern "C" {
        fn hp_zt_manager_abi_version() -> u32;
        fn hp_zt_stream_abi_version() -> u32;
        fn hp_zt_network_join(owner: u64, network: u64, timeout: u32, lease: *mut u64) -> i32;
        fn hp_zt_network_status(
            owner: u64,
            lease: u64,
            timeout: u32,
            phase: *mut u32,
            online: *mut u32,
        ) -> i32;
        fn hp_zt_network_leave(owner: u64, lease: u64, timeout: u32) -> i32;
        fn hp_zt_stream_new(
            owner: u64,
            lease: u64,
            ip: *const u8,
            len: u32,
            port: u16,
            stream: *mut u64,
        ) -> i32;
        fn hp_zt_stream_open(owner: u64, lease: u64, stream: u64, timeout: u32) -> i32;
        fn hp_zt_stream_read(
            owner: u64,
            lease: u64,
            stream: u64,
            output: *mut u8,
            cap: u32,
            timeout: u32,
            len: *mut u32,
        ) -> i32;
        fn hp_zt_stream_write(
            owner: u64,
            lease: u64,
            stream: u64,
            bytes: *const u8,
            len: u32,
            timeout: u32,
            written: *mut u32,
        ) -> i32;
        fn hp_zt_stream_shutdown_write(owner: u64, lease: u64, stream: u64, timeout: u32) -> i32;
        fn hp_zt_stream_cancel(owner: u64, lease: u64, stream: u64) -> i32;
        fn hp_zt_stream_close(owner: u64, lease: u64, stream: u64, timeout: u32) -> i32;
        fn hp_zt_stream_release(owner: u64, lease: u64, stream: u64) -> i32;
    }
    pub(super) fn presence() -> Result<()> {
        // SAFETY: fixed explicit library; no node start or storage callback.
        if unsafe { hp_zt_manager_abi_version() == 1 && hp_zt_stream_abi_version() == 1 } {
            Ok(())
        } else {
            Err(Failure::ProviderUnavailable)
        }
    }
    fn milliseconds(value: Duration) -> Result<u32> {
        if value.is_zero() || value > MAX_DEADLINE {
            return Err(Failure::InvalidDeadline);
        }
        Ok(value.as_millis().max(1) as u32)
    }
    fn failure(code: i32) -> Failure {
        match code {
            STALE => Failure::StaleRevision,
            BUSY => Failure::Busy,
            TIMEOUT => Failure::WaitTimeout,
            CAPACITY => Failure::Capacity,
            CLOSING | CANCELLED => Failure::Cancelled,
            _ => Failure::NativeRejected(code),
        }
    }
    fn remaining(until: Instant) -> Result<Duration> {
        until
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or(Failure::WaitTimeout)
    }
    #[derive(Clone, Copy)]
    struct Route {
        owner: u64,
        network: u64,
    }
    struct State {
        session: Option<Arc<dyn NativeDeviceSession>>,
        owner: u64,
        network: Option<u64>,
        streams: HashSet<u64>,
        closing: bool,
        retired: bool,
        started: bool,
    }
    pub(super) struct Native {
        spec: NodeSpec,
        state: Mutex<State>,
    }
    impl Native {
        pub(super) fn new(spec: &NodeSpec) -> Result<Self> {
            validate_spec(spec)?;
            presence()?;
            Ok(Self {
                spec: spec.clone(),
                state: Mutex::new(State {
                    session: None,
                    owner: 0,
                    network: None,
                    streams: HashSet::new(),
                    closing: false,
                    retired: false,
                    started: false,
                }),
            })
        }
        pub(super) fn start(
            &self,
            source: Arc<dyn NativeDeviceSource>,
            deadline: Duration,
            cancel: &AtomicBool,
        ) -> Result<()> {
            milliseconds(deadline)?;
            let until = Instant::now() + deadline;
            if cancel.load(Ordering::Acquire) {
                return Err(Failure::Cancelled);
            }
            {
                let mut state = lock(&self.state);
                if state.started || state.closing || state.retired {
                    return Err(Failure::Busy);
                }
                state.started = true;
            }
            // This acquisition runs inside NodeEntry's original start call, never
            // in its discardable load stage. Late custody reaches managed_stop.
            let config = source.acquire(&self.spec, deadline)?;
            let mut state = lock(&self.state);
            let same =
                config.spec == self.spec && config.session.identity_ref() == self.spec.identity_ref;
            state.owner = config.session.owner();
            state.session = Some(config.session);
            if !same {
                state.closing = true;
                return Err(Failure::InvalidRoute);
            }
            if let Some(error) = config.startup_failure {
                state.closing = true;
                return Err(error);
            }
            if state.owner == 0 {
                state.closing = true;
                return Err(Failure::IdentityUnavailable);
            }
            if cancel.load(Ordering::Acquire) || state.closing || state.retired {
                state.closing = true;
                return Err(Failure::Cancelled);
            }
            let ms = milliseconds(remaining(until).inspect_err(|_| state.closing = true)?)?;
            let mut network = 0;
            // SAFETY: exact immutable native owner; output remains valid through return.
            let code = unsafe {
                hp_zt_network_join(
                    state.owner,
                    network_id(&self.spec.network)?,
                    ms,
                    &mut network,
                )
            };
            if network != 0 {
                state.network = Some(network);
            }
            if code != OK {
                state.closing = true;
                return Err(failure(code));
            }
            if network == 0 {
                state.closing = true;
                return Err(Failure::InvalidNativeResponse);
            }
            if cancel.load(Ordering::Acquire) {
                state.closing = true;
                return Err(Failure::Cancelled);
            }
            Ok(())
        }
        fn route(&self, stream: Option<u64>) -> Result<Route> {
            let state = lock(&self.state);
            if state.closing || state.retired {
                return Err(Failure::ProfileUnavailable);
            }
            if stream.is_some_and(|id| !state.streams.contains(&id)) {
                return Err(Failure::WrongOwner);
            }
            Ok(Route {
                owner: state.owner,
                network: state.network.ok_or(Failure::ProfileUnavailable)?,
            })
        }
        pub(super) fn status(&self) -> Result<NodeStatus> {
            let state = lock(&self.state);
            if state.retired {
                return Ok(NodeStatus::Stopped);
            }
            if state.closing {
                return Ok(NodeStatus::Closing);
            }
            let Some(network) = state.network else {
                return Ok(NodeStatus::Starting);
            };
            let mut phase = 0;
            let mut online = 0;
            let code = unsafe {
                hp_zt_network_status(state.owner, network, 1000, &mut phase, &mut online)
            };
            if code != OK {
                return Err(failure(code));
            }
            if online > 1 {
                return Err(Failure::InvalidNativeResponse);
            }
            let phase = match phase {
                1 => NetworkPhase::Requesting,
                2 => NetworkPhase::Configured,
                3 => NetworkPhase::Denied,
                4 => NetworkPhase::NotFound,
                5 => NetworkPhase::PortError,
                6 => NetworkPhase::ClientOld,
                7 => NetworkPhase::AuthRequired,
                8 => return Ok(NodeStatus::Closing),
                9 => NetworkPhase::Unknown,
                _ => return Err(Failure::InvalidNativeResponse),
            };
            Ok(NodeStatus::ZeroTier {
                phase,
                online: online == 1,
            })
        }
        fn close_route(route: Route, stream: u64, ms: u32) -> Result<()> {
            let _ = unsafe { hp_zt_stream_cancel(route.owner, route.network, stream) };
            let code = unsafe { hp_zt_stream_close(route.owner, route.network, stream, ms) };
            if code != OK {
                return Err(Failure::ClosePending);
            }
            let code = unsafe { hp_zt_stream_release(route.owner, route.network, stream) };
            if code != OK {
                return Err(Failure::ClosePending);
            }
            Ok(())
        }
        pub(super) fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
            let ms = milliseconds(deadline)?;
            if port == 0 {
                return Err(Failure::InvalidRoute);
            }
            let ip: IpAddr = host.parse().map_err(|_| Failure::InvalidRoute)?;
            let bytes: Vec<u8> = match ip {
                IpAddr::V4(ip) => ip.octets().to_vec(),
                IpAddr::V6(ip) => ip.octets().to_vec(),
            };
            let mut stream = 0;
            let route;
            {
                let mut state = lock(&self.state);
                if state.closing || state.retired {
                    return Err(Failure::ProfileUnavailable);
                }
                route = Route {
                    owner: state.owner,
                    network: state.network.ok_or(Failure::ProfileUnavailable)?,
                };
                let code = unsafe {
                    hp_zt_stream_new(
                        route.owner,
                        route.network,
                        bytes.as_ptr(),
                        bytes.len() as u32,
                        port,
                        &mut stream,
                    )
                };
                if stream != 0 {
                    state.streams.insert(stream);
                }
                if code != OK {
                    return Err(failure(code));
                }
                if stream == 0 {
                    return Err(Failure::InvalidNativeResponse);
                }
            }
            let code = unsafe { hp_zt_stream_open(route.owner, route.network, stream, ms) };
            if code == OK {
                return Ok(stream);
            }
            // Failed-open handles remain bounded and attached to this original
            // backend if native close cannot yet prove retirement. Stop retries.
            if self.close(stream).is_ok() {
                debug_assert!(!lock(&self.state).streams.contains(&stream));
            }
            Err(failure(code))
        }
        pub(super) fn read(&self, stream: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
            if max == 0 || max > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            let route = self.route(Some(stream))?;
            let mut bytes = vec![0; max];
            let mut len = 0;
            let code = unsafe {
                hp_zt_stream_read(
                    route.owner,
                    route.network,
                    stream,
                    bytes.as_mut_ptr(),
                    max as u32,
                    milliseconds(deadline)?,
                    &mut len,
                )
            };
            if len as usize > max {
                return Err(Failure::InvalidNativeResponse);
            }
            if code == TIMEOUT && len == 0 {
                return Err(Failure::ReadTimedOut);
            }
            if code != OK {
                return Err(failure(code));
            }
            bytes.truncate(len as usize);
            Ok(bytes)
        }
        pub(super) fn write(&self, stream: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
            if bytes.is_empty() || bytes.len() > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            let route = self.route(Some(stream))?;
            let mut accepted = 0;
            let code = unsafe {
                hp_zt_stream_write(
                    route.owner,
                    route.network,
                    stream,
                    bytes.as_ptr(),
                    bytes.len() as u32,
                    milliseconds(deadline)?,
                    &mut accepted,
                )
            };
            if code != OK || accepted == 0 || accepted as usize > bytes.len() {
                return Err(Failure::UnknownWrite);
            }
            Ok(accepted as usize)
        }
        pub(super) fn shutdown(&self, stream: u64, deadline: Duration) -> Result<()> {
            let route = self.route(Some(stream))?;
            let code = unsafe {
                hp_zt_stream_shutdown_write(
                    route.owner,
                    route.network,
                    stream,
                    milliseconds(deadline)?,
                )
            };
            if code == OK {
                Ok(())
            } else {
                Err(failure(code))
            }
        }
        pub(super) fn close(&self, stream: u64) -> Result<()> {
            let mut state = lock(&self.state);
            if !state.streams.contains(&stream) {
                return Ok(());
            }
            let route = Route {
                owner: state.owner,
                network: state.network.ok_or(Failure::ClosePending)?,
            };
            Self::close_route(route, stream, 60000)?;
            state.streams.remove(&stream);
            Ok(())
        }
        pub(super) fn stop(&self, deadline: Duration) -> Result<()> {
            milliseconds(deadline)?;
            let until = Instant::now() + deadline;
            let mut state = lock(&self.state);
            state.closing = true;
            if state.retired {
                return Ok(());
            }
            if let Some(network) = state.network {
                let route = Route {
                    owner: state.owner,
                    network,
                };
                for stream in state.streams.iter().copied().collect::<Vec<_>>() {
                    Self::close_route(route, stream, milliseconds(remaining(until)?)?)?;
                    state.streams.remove(&stream);
                }
                let code = unsafe {
                    hp_zt_network_leave(state.owner, network, milliseconds(remaining(until)?)?)
                };
                if code != OK {
                    return Err(failure(code));
                }
                state.network = None;
            }
            if let Some(session) = &state.session {
                session.retire_after_network(remaining(until)?)?;
            }
            state.session = None;
            state.retired = true;
            Ok(())
        }
    }
}

pub struct ZeroTierBackend {
    #[cfg(feature = "linked-zerotier")]
    native: linked::Native,
}
impl ZeroTierBackend {
    pub(crate) fn managed(spec: &NodeSpec) -> Result<Self> {
        #[cfg(feature = "linked-zerotier")]
        {
            Ok(Self {
                native: linked::Native::new(spec)?,
            })
        }
        #[cfg(not(feature = "linked-zerotier"))]
        {
            let _ = spec;
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn start_node(
        &self,
        source: Arc<dyn NativeDeviceSource>,
        deadline: Duration,
        cancelled: &AtomicBool,
    ) -> Result<()> {
        #[cfg(feature = "linked-zerotier")]
        {
            self.native.start(source, deadline, cancelled)
        }
        #[cfg(not(feature = "linked-zerotier"))]
        {
            let _ = (source, deadline, cancelled);
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn node_status(&self) -> Result<NodeStatus> {
        #[cfg(feature = "linked-zerotier")]
        {
            self.native.status()
        }
        #[cfg(not(feature = "linked-zerotier"))]
        {
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn stop_node(&self, deadline: Duration) -> Result<()> {
        #[cfg(feature = "linked-zerotier")]
        {
            self.native.stop(deadline)
        }
        #[cfg(not(feature = "linked-zerotier"))]
        {
            let _ = deadline;
            Err(Failure::ProviderUnavailable)
        }
    }
}
macro_rules! native_or_unavailable {
    ($self:ident, $method:ident($($arg:ident),*)) => {{
        #[cfg(feature = "linked-zerotier")]
        { $self.native.$method($($arg),*) }
        #[cfg(not(feature = "linked-zerotier"))]
        { let _ = ($($arg,)*); Err(Failure::ProviderUnavailable) }
    }};
}
impl Backend for ZeroTierBackend {
    fn provider(&self) -> Provider {
        Provider::ZeroTier
    }
    fn evidence(&self) -> Evidence {
        if cfg!(feature = "zerotier-fixture") {
            Evidence::SyntheticNativeFixture
        } else {
            Evidence::CandidateAbiOnly
        }
    }
    fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
        native_or_unavailable!(self, open(host, port, deadline))
    }
    fn read(&self, handle: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
        native_or_unavailable!(self, read(handle, max, deadline))
    }
    fn write(&self, handle: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
        native_or_unavailable!(self, write(handle, bytes, deadline))
    }
    fn shutdown_write(&self, handle: u64, deadline: Duration) -> Result<()> {
        native_or_unavailable!(self, shutdown(handle, deadline))
    }
    fn close(&self, handle: u64) -> Result<()> {
        native_or_unavailable!(self, close(handle))
    }
}
pub fn verify_managed_abi_presence() -> Result<()> {
    #[cfg(feature = "linked-zerotier")]
    {
        linked::presence()
    }
    #[cfg(not(feature = "linked-zerotier"))]
    {
        Err(Failure::ProviderUnavailable)
    }
}

#[cfg(test)]
mod tests;

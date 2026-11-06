//! Explicit managed tsnet ABI. Store bytes remain in host native custody; there
//! is no disk-store, system TCP, environment credential or fixture fallback.
use crate::nodes::{NodeSpec, NodeStatus};
use crate::{Backend, Evidence, Failure, Provider, Result};
#[cfg(feature = "linked-tailscale")]
use crate::{MAX_DEADLINE, MAX_IO};
use std::path::{Component, PathBuf};
use std::sync::Arc;
use std::time::Duration;

pub const MAX_STATE_KEY: usize = 1024;
pub const MAX_STATE_VALUE: usize = 262_144;
pub const MAX_AUTH_URL: usize = 4096;
#[cfg(feature = "linked-tailscale")]
const MAX_STATUS: usize = 8192;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StateStoreError {
    Missing,
    Unavailable,
}
pub type StateStoreResult<T> = std::result::Result<T, StateStoreError>;
/// Thread-safe native host custody. Keys are arbitrary bytes, including NUL and
/// empty. Missing differs from a present empty value; None writes delete.
/// Implementations must not log/serialize state or fall back to plaintext files.
pub trait NativeStateStore: Send + Sync + 'static {
    fn read(&self, key: &[u8]) -> StateStoreResult<Vec<u8>>;
    fn write(&self, key: &[u8], value: Option<&[u8]>) -> StateStoreResult<()>;
}
pub trait NativeStateSource: Send + Sync + 'static {
    fn load(&self, spec: &NodeSpec) -> Result<NativeNodeConfig>;
}
/// The host must obtain this path from its native app-private directory policy,
/// checking ownership, permissions and symlinks before construction. This type
/// checks lexical shape only; it is not proof of platform storage protection.
#[cfg_attr(not(feature = "linked-tailscale"), allow(dead_code))]
pub struct NativeVettedDirectory(PathBuf);
impl NativeVettedDirectory {
    pub fn from_native_vetted(path: PathBuf) -> Result<Self> {
        let text = path.to_str().ok_or(Failure::InvalidRoute)?;
        if !path.is_absolute()
            || text.len() > 4096
            || text.chars().any(char::is_control)
            || path.components().collect::<PathBuf>().as_os_str() != path.as_os_str()
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
        {
            return Err(Failure::InvalidRoute);
        }
        Ok(Self(path))
    }
}
/// No Debug/Clone/serde: contains native custody, not just public metadata.
#[cfg_attr(not(feature = "linked-tailscale"), allow(dead_code))]
pub struct NativeNodeConfig {
    spec: NodeSpec,
    directory: NativeVettedDirectory,
    hostname: String,
    control_url: String,
    store: Arc<dyn NativeStateStore>,
}
impl NativeNodeConfig {
    pub fn for_spec(
        spec: &NodeSpec,
        directory: NativeVettedDirectory,
        hostname: String,
        control_url: String,
        store: Arc<dyn NativeStateStore>,
    ) -> Result<Self> {
        if spec.profile.provider != Provider::Tailscale
            || hostname.is_empty()
            || hostname.len() > 63
            || !hostname
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-')
            || hostname.starts_with('-')
            || hostname.ends_with('-')
            || !reviewed_https(&control_url)
            || control_url.contains('?')
        {
            return Err(Failure::InvalidRoute);
        }
        Ok(Self {
            spec: spec.clone(),
            directory,
            hostname,
            control_url,
            store,
        })
    }
}
/// A bounded reviewed HTTPS URL returned only by an explicit login operation.
/// Debug is deliberately redacted because URL query/path may authorize login.
#[derive(Clone, Eq, PartialEq)]
pub struct ReviewedAuthUrl(String);
impl ReviewedAuthUrl {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}
impl std::fmt::Debug for ReviewedAuthUrl {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ReviewedAuthUrl(<redacted>)")
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoginStatus {
    pub state: NodeStatus,
    pub auth_url: Option<ReviewedAuthUrl>,
}

// A deliberately narrow URL policy, shared by control and authorization URLs:
// ASCII HTTPS authority, optional numeric port, no credentials/fragment/escapes
// in authority and no control, whitespace or backslash anywhere. IPv6 literals
// are not admitted by this prototype. The host still reviews the destination.
fn reviewed_https(value: &str) -> bool {
    if value.is_empty()
        || value.len() > MAX_AUTH_URL
        || !value.is_ascii()
        || value
            .bytes()
            .any(|b| b <= 32 || b == 127 || b == b'\\' || b == b'#')
    {
        return false;
    }
    let Some(rest) = value.strip_prefix("https://") else {
        return false;
    };
    let authority = rest.split(['/', '?']).next().unwrap_or("");
    if authority.is_empty() || authority.len() > 259 || authority.contains(['@', '%', '[', ']']) {
        return false;
    }
    let (host, port) = authority
        .rsplit_once(':')
        .map_or((authority, None), |(host, port)| (host, Some(port)));
    if host.is_empty()
        || host.len() > 253
        || host.starts_with('.')
        || host.ends_with('.')
        || !host
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        || host
            .split('.')
            .any(|part| part.is_empty() || part.starts_with('-') || part.ends_with('-'))
    {
        return false;
    }
    port.is_none_or(|p| {
        !p.is_empty()
            && p.bytes().all(|b| b.is_ascii_digit())
            && p.parse::<u16>().is_ok_and(|n| n > 0)
    })
}

#[cfg(feature = "linked-tailscale")]
mod linked {
    use super::*;
    use crate::lock;
    use std::collections::HashMap;
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::sync::{
        Mutex, OnceLock,
        atomic::{AtomicBool, AtomicU64, Ordering},
    };
    const OK: i32 = 0;
    const NOT_FOUND: i32 = 2;
    const TIMEOUT: i32 = 5;
    const IO: i32 = 8;
    const MAX_BUFFERS: usize = 32;
    #[repr(C)]
    pub(super) struct StoreCallbacks {
        read: unsafe extern "C" fn(u64, *const u8, u32, *mut *mut u8, *mut u32, *mut u32) -> i32,
        write: unsafe extern "C" fn(u64, *const u8, u32, *const u8, u32, u32) -> i32,
        release: unsafe extern "C" fn(u64, *mut u8, u32),
    }
    #[link(name = "hp_tailscale")]
    unsafe extern "C" {
        pub(super) fn hp_ts_abi_version() -> u32;
        fn hp_ts_node_new(
            config: *mut u8,
            len: u32,
            store: *mut StoreCallbacks,
            context: u64,
            node: *mut u64,
        ) -> i32;
        fn hp_ts_node_start(node: u64, timeout_ms: u32) -> i32;
        fn hp_ts_node_status(
            node: u64,
            timeout_ms: u32,
            data: *mut u8,
            cap: u32,
            len: *mut u32,
        ) -> i32;
        fn hp_ts_node_begin_login(node: u64, timeout_ms: u32) -> i32;
        fn hp_ts_node_dial(
            node: u64,
            address: *mut u8,
            len: u32,
            timeout_ms: u32,
            stream: *mut u64,
        ) -> i32;
        fn hp_ts_stream_read(
            stream: u64,
            data: *mut u8,
            cap: u32,
            timeout_ms: u32,
            len: *mut u32,
        ) -> i32;
        fn hp_ts_stream_write(
            stream: u64,
            data: *mut u8,
            len: u32,
            timeout_ms: u32,
            written: *mut u32,
        ) -> i32;
        fn hp_ts_stream_shutdown_write(stream: u64, timeout_ms: u32) -> i32;
        fn hp_ts_stream_close(stream: u64, timeout_ms: u32) -> i32;
        fn hp_ts_stream_release(stream: u64) -> i32;
        fn hp_ts_node_close(node: u64, timeout_ms: u32) -> i32;
        fn hp_ts_node_release(node: u64) -> i32;
    }
    struct SecretBuffer(Vec<u8>);
    impl Drop for SecretBuffer {
        fn drop(&mut self) {
            for byte in &mut self.0 {
                unsafe {
                    std::ptr::write_volatile(byte, 0);
                }
            }
        }
    }
    struct CallbackContext {
        store: Arc<dyn NativeStateStore>,
        buffers: Mutex<HashMap<usize, SecretBuffer>>,
        callbacks: Box<StoreCallbacks>,
    }
    static NEXT_CONTEXT: AtomicU64 = AtomicU64::new(1);
    static CONTEXTS: OnceLock<Mutex<HashMap<u64, Arc<CallbackContext>>>> = OnceLock::new();
    fn contexts() -> &'static Mutex<HashMap<u64, Arc<CallbackContext>>> {
        CONTEXTS.get_or_init(|| Mutex::new(HashMap::new()))
    }
    fn register(store: Arc<dyn NativeStateStore>) -> Result<u64> {
        let mut all = lock(contexts());
        if all.len() >= crate::nodes::MAX_NODES {
            return Err(Failure::Capacity);
        }
        let id = NEXT_CONTEXT
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| Failure::Capacity)?;
        all.insert(
            id,
            Arc::new(CallbackContext {
                store,
                buffers: Mutex::new(HashMap::new()),
                callbacks: Box::new(callbacks()),
            }),
        );
        Ok(id)
    }
    fn context(id: u64) -> Option<Arc<CallbackContext>> {
        lock(contexts()).get(&id).cloned()
    }
    fn unregister(id: u64) {
        let owned = { lock(contexts()).remove(&id) };
        // Host custody destructors may attach native threads. Do not run them
        // under the global context registry mutex.
        drop(owned);
    }
    unsafe fn input<'a>(data: *const u8, len: u32, max: usize) -> Option<&'a [u8]> {
        if len as usize > max || (data.is_null() && len != 0) {
            return None;
        }
        // SAFETY: caller follows the pinned borrowed-buffer ABI. Zero permits NULL.
        Some(if len == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(data, len as usize) }
        })
    }
    unsafe extern "C" fn read(
        id: u64,
        key: *const u8,
        key_len: u32,
        data: *mut *mut u8,
        len: *mut u32,
        found: *mut u32,
    ) -> i32 {
        catch_unwind(AssertUnwindSafe(|| {
            if data.is_null() || len.is_null() || found.is_null() {
                return IO;
            }
            unsafe {
                *data = std::ptr::null_mut();
                *len = 0;
                *found = 0;
            }
            let Some(key) = (unsafe { input(key, key_len, MAX_STATE_KEY) }) else {
                return IO;
            };
            let Some(ctx) = context(id) else {
                return IO;
            };
            let value = match ctx.store.read(key) {
                Ok(value) => value,
                Err(StateStoreError::Missing) => return OK,
                Err(_) => return IO,
            };
            let mut value = SecretBuffer(value);
            if value.0.len() > MAX_STATE_VALUE {
                return IO;
            }
            unsafe {
                *found = 1;
            }
            if value.0.is_empty() {
                return OK;
            }
            let mut buffers = lock(&ctx.buffers);
            if buffers.len() >= MAX_BUFFERS {
                return IO;
            }
            let pointer = value.0.as_mut_ptr();
            let count = value.0.len() as u32;
            buffers.insert(pointer as usize, value);
            unsafe {
                *data = pointer;
                *len = count;
            }
            OK
        }))
        .unwrap_or(IO)
    }
    unsafe extern "C" fn write(
        id: u64,
        key: *const u8,
        key_len: u32,
        data: *const u8,
        len: u32,
        delete: u32,
    ) -> i32 {
        catch_unwind(AssertUnwindSafe(|| {
            let Some(key) = (unsafe { input(key, key_len, MAX_STATE_KEY) }) else {
                return IO;
            };
            if delete > 1 || (delete == 1 && len != 0) {
                return IO;
            }
            let value = if delete == 1 {
                None
            } else {
                let Some(bytes) = (unsafe { input(data, len, MAX_STATE_VALUE) }) else {
                    return IO;
                };
                Some(bytes)
            };
            let Some(ctx) = context(id) else {
                return IO;
            };
            match ctx.store.write(key, value) {
                Ok(()) => OK,
                Err(_) => IO,
            }
        }))
        .unwrap_or(IO)
    }
    unsafe extern "C" fn release(id: u64, data: *mut u8, len: u32) {
        let _ = catch_unwind(AssertUnwindSafe(|| {
            let Some(ctx) = context(id) else {
                return;
            };
            let mut buffers = lock(&ctx.buffers);
            if buffers
                .get(&(data as usize))
                .is_some_and(|value| value.0.len() == len as usize)
            {
                buffers.remove(&(data as usize));
            }
        }));
    }
    fn callbacks() -> StoreCallbacks {
        StoreCallbacks {
            read,
            write,
            release,
        }
    }
    fn milliseconds(deadline: Duration) -> Result<u32> {
        if deadline.is_zero() || deadline > MAX_DEADLINE {
            return Err(Failure::InvalidDeadline);
        }
        Ok(deadline.as_millis().max(1) as u32)
    }
    fn json_string(value: &str) -> String {
        let mut result = String::from("\"");
        for c in value.chars() {
            match c {
                '"' => result.push_str("\\\""),
                '\\' => result.push_str("\\\\"),
                c if c.is_control() => {
                    use std::fmt::Write;
                    let _ = write!(result, "\\u{:04x}", c as u32);
                }
                c => result.push(c),
            }
        }
        result.push('"');
        result
    }
    pub(super) struct Native {
        expected: NodeSpec,
        node: AtomicU64,
        context: AtomicU64,
        login: AtomicBool,
    }
    impl Native {
        pub(super) fn new(spec: &NodeSpec) -> Result<Self> {
            if unsafe { hp_ts_abi_version() } != 1 {
                return Err(Failure::InvalidNativeResponse);
            }
            Ok(Self {
                expected: spec.clone(),
                node: AtomicU64::new(0),
                context: AtomicU64::new(0),
                login: AtomicBool::new(false),
            })
        }
        pub(super) fn start(&self, config: NativeNodeConfig, deadline: Duration) -> Result<()> {
            if config.spec != self.expected
                || self.node.load(Ordering::Acquire) != 0
                || self.context.load(Ordering::Acquire) != 0
            {
                return Err(Failure::InvalidRoute);
            }
            let id = register(config.store)?;
            self.context.store(id, Ordering::Release);
            let text = format!(
                "{{\"directory\":{},\"hostname\":{},\"control_url\":{}}}",
                json_string(config.directory.0.to_str().ok_or(Failure::InvalidRoute)?),
                json_string(&config.hostname),
                json_string(&config.control_url)
            );
            let mut bytes = text.into_bytes();
            let mut node = 0;
            // SAFETY: config and the pinned callback table remain owned through
            // synchronous return. The context registry lives until release OK.
            let code = unsafe {
                hp_ts_node_new(
                    bytes.as_mut_ptr(),
                    bytes.len() as u32,
                    (&*context(id).ok_or(Failure::IdentityUnavailable)?.callbacks
                        as *const StoreCallbacks)
                        .cast_mut(),
                    id,
                    &mut node,
                )
            };
            self.node.store(node, Ordering::Release);
            if code != OK {
                if node == 0 {
                    unregister(id);
                    self.context.store(0, Ordering::Release);
                }
                return Err(Failure::NativeRejected(code));
            }
            if node == 0 {
                return Err(Failure::InvalidNativeResponse);
            }
            let code = unsafe { hp_ts_node_start(node, milliseconds(deadline)?) };
            if code == OK {
                Ok(())
            } else {
                Err(Failure::NativeRejected(code))
            }
        }
        pub(super) fn status(&self, deadline: Duration) -> Result<LoginStatus> {
            let mut bytes = vec![0; MAX_STATUS];
            let mut len = 0;
            let code = unsafe {
                hp_ts_node_status(
                    self.node.load(Ordering::Acquire),
                    milliseconds(deadline)?,
                    bytes.as_mut_ptr(),
                    bytes.len() as u32,
                    &mut len,
                )
            };
            if code != OK {
                return Err(Failure::NativeRejected(code));
            }
            if len as usize > bytes.len() {
                return Err(Failure::InvalidNativeResponse);
            }
            bytes.truncate(len as usize);
            let (state, url) = parse_status(&bytes)?;
            let auth_url = if url.is_empty() {
                None
            } else {
                if !self.login.load(Ordering::Acquire) || !reviewed_https(&url) {
                    return Err(Failure::InvalidNativeResponse);
                }
                Some(ReviewedAuthUrl(url))
            };
            Ok(LoginStatus { state, auth_url })
        }
        pub(super) fn login(&self, deadline: Duration) -> Result<LoginStatus> {
            self.login.store(true, Ordering::Release);
            let code = unsafe {
                hp_ts_node_begin_login(self.node.load(Ordering::Acquire), milliseconds(deadline)?)
            };
            if code != OK {
                return Err(Failure::NativeRejected(code));
            }
            self.status(deadline)
        }
        pub(super) fn stop(&self, deadline: Duration) -> Result<()> {
            let node = self.node.load(Ordering::Acquire);
            if node == 0 {
                return if self.context.load(Ordering::Acquire) == 0 {
                    Ok(())
                } else {
                    Err(Failure::ClosePending)
                };
            }
            let closed = unsafe { hp_ts_node_close(node, milliseconds(deadline)?) };
            if closed != OK {
                return Err(Failure::ClosePending);
            }
            // Release is the proof of real close plus all original FFI/callback
            // work converging. A timeout alone never frees store ownership.
            if unsafe { hp_ts_node_release(node) } != OK {
                return Err(Failure::ClosePending);
            }
            self.node.store(0, Ordering::Release);
            let id = self.context.swap(0, Ordering::AcqRel);
            unregister(id);
            Ok(())
        }
        pub(super) fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
            let mut address = format!("{host}:{port}").into_bytes();
            let mut stream = 0;
            let code = unsafe {
                hp_ts_node_dial(
                    self.node.load(Ordering::Acquire),
                    address.as_mut_ptr(),
                    address.len() as u32,
                    milliseconds(deadline)?,
                    &mut stream,
                )
            };
            if code != OK {
                return Err(Failure::NativeRejected(code));
            }
            if stream == 0 {
                Err(Failure::InvalidNativeResponse)
            } else {
                Ok(stream)
            }
        }
        pub(super) fn read(&self, handle: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
            if max == 0 || max > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            let mut bytes = vec![0; max];
            let mut len = 0;
            let code = unsafe {
                hp_ts_stream_read(
                    handle,
                    bytes.as_mut_ptr(),
                    max as u32,
                    milliseconds(deadline)?,
                    &mut len,
                )
            };
            if code == TIMEOUT && len == 0 {
                return Err(Failure::ReadTimedOut);
            }
            if code != OK {
                return Err(Failure::NativeRead(code));
            }
            if len as usize > bytes.len() {
                return Err(Failure::InvalidNativeResponse);
            }
            bytes.truncate(len as usize);
            Ok(bytes)
        }
        pub(super) fn write(&self, handle: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
            if bytes.is_empty() || bytes.len() > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            // Native promises to borrow without mutation despite cgo's generated pointer type.
            let code_and_count = {
                let mut count = 0;
                let code = unsafe {
                    hp_ts_stream_write(
                        handle,
                        bytes.as_ptr().cast_mut(),
                        bytes.len() as u32,
                        milliseconds(deadline)?,
                        &mut count,
                    )
                };
                (code, count)
            };
            if code_and_count.0 != OK || code_and_count.1 == 0 {
                return Err(Failure::UnknownWrite);
            }
            if code_and_count.1 as usize > bytes.len() {
                Err(Failure::InvalidNativeResponse)
            } else {
                Ok(code_and_count.1 as usize)
            }
        }
        pub(super) fn shutdown(&self, handle: u64, deadline: Duration) -> Result<()> {
            if unsafe { hp_ts_stream_shutdown_write(handle, milliseconds(deadline)?) } == OK {
                Ok(())
            } else {
                Err(Failure::UnknownWrite)
            }
        }
        pub(super) fn close(&self, handle: u64) -> Result<()> {
            let code = unsafe { hp_ts_stream_close(handle, MAX_DEADLINE.as_millis() as u32) };
            if code != OK && code != NOT_FOUND {
                return Err(Failure::ClosePending);
            }
            let released = unsafe { hp_ts_stream_release(handle) };
            if released == OK || released == NOT_FOUND {
                Ok(())
            } else {
                Err(Failure::ClosePending)
            }
        }
    }
    pub(super) fn presence() -> Result<()> {
        std::hint::black_box([
            hp_ts_node_new as *const (),
            hp_ts_node_start as *const (),
            hp_ts_node_status as *const (),
            hp_ts_node_begin_login as *const (),
            hp_ts_node_dial as *const (),
            hp_ts_stream_read as *const (),
            hp_ts_stream_write as *const (),
            hp_ts_stream_shutdown_write as *const (),
            hp_ts_stream_close as *const (),
            hp_ts_stream_release as *const (),
            hp_ts_node_close as *const (),
            hp_ts_node_release as *const (),
        ]);
        if unsafe { hp_ts_abi_version() } != 1 {
            return Err(Failure::InvalidNativeResponse);
        }
        let mut data = [0; 128];
        let mut len = 0;
        let code =
            unsafe { hp_ts_node_status(0, 1, data.as_mut_ptr(), data.len() as u32, &mut len) };
        if code == NOT_FOUND {
            Ok(())
        } else {
            Err(Failure::InvalidNativeResponse)
        }
    }
    // No Drop unregister: failed stop or an abandoned runtime may still have
    // native callbacks. The bounded registry intentionally retains that owner.
    pub(super) fn parse_status(bytes: &[u8]) -> Result<(NodeStatus, String)> {
        struct Json<'a> {
            bytes: &'a [u8],
            at: usize,
        }
        impl Json<'_> {
            fn ws(&mut self) {
                while self
                    .bytes
                    .get(self.at)
                    .is_some_and(|b| b" \t\r\n".contains(b))
                {
                    self.at += 1;
                }
            }
            fn take(&mut self, byte: u8) -> Result<()> {
                self.ws();
                if self.bytes.get(self.at) != Some(&byte) {
                    return Err(Failure::InvalidNativeResponse);
                }
                self.at += 1;
                Ok(())
            }
            fn string(&mut self) -> Result<String> {
                self.take(b'"')?;
                let mut text = String::new();
                loop {
                    let b = *self
                        .bytes
                        .get(self.at)
                        .ok_or(Failure::InvalidNativeResponse)?;
                    self.at += 1;
                    match b {
                        b'"' => return Ok(text),
                        b'\\' => {
                            let e = *self
                                .bytes
                                .get(self.at)
                                .ok_or(Failure::InvalidNativeResponse)?;
                            self.at += 1;
                            match e {
                                b'"' | b'\\' | b'/' => text.push(e as char),
                                b'u' => {
                                    let raw = self
                                        .bytes
                                        .get(self.at..self.at + 4)
                                        .ok_or(Failure::InvalidNativeResponse)?;
                                    self.at += 4;
                                    let n = u8::from_str_radix(
                                        std::str::from_utf8(raw)
                                            .map_err(|_| Failure::InvalidNativeResponse)?,
                                        16,
                                    )
                                    .map_err(|_| Failure::InvalidNativeResponse)?;
                                    if !(32..127).contains(&n) {
                                        return Err(Failure::InvalidNativeResponse);
                                    }
                                    text.push(n as char);
                                }
                                _ => return Err(Failure::InvalidNativeResponse),
                            }
                        }
                        32..=126 => text.push(b as char),
                        _ => return Err(Failure::InvalidNativeResponse),
                    }
                }
            }
        }
        let mut json = Json { bytes, at: 0 };
        json.take(b'{')?;
        let mut state = None;
        let mut auth = None;
        for index in 0..2 {
            if index != 0 {
                json.take(b',')?;
            }
            let key = json.string()?;
            json.take(b':')?;
            let value = json.string()?;
            match key.as_str() {
                "state" if state.is_none() => state = Some(value),
                "auth_url" if auth.is_none() => auth = Some(value),
                _ => return Err(Failure::InvalidNativeResponse),
            }
        }
        json.take(b'}')?;
        json.ws();
        if json.at != bytes.len() {
            return Err(Failure::InvalidNativeResponse);
        }
        let state = match state.as_deref() {
            Some("Starting") => NodeStatus::Starting,
            Some("NeedsLogin") => NodeStatus::NeedsLogin,
            Some("NeedsMachineAuth") => NodeStatus::NeedsMachineAuth,
            Some("Running") => NodeStatus::Running,
            Some("Closing") => NodeStatus::Closing,
            Some("Stopped") => NodeStatus::Stopped,
            _ => return Err(Failure::InvalidNativeResponse),
        };
        Ok((state, auth.ok_or(Failure::InvalidNativeResponse)?))
    }
}

pub struct TailscaleBackend {
    #[cfg(feature = "linked-tailscale")]
    native: linked::Native,
}
impl TailscaleBackend {
    pub(crate) fn managed(spec: &NodeSpec) -> Result<Self> {
        #[cfg(feature = "linked-tailscale")]
        {
            Ok(Self {
                native: linked::Native::new(spec)?,
            })
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = spec;
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn start_node(&self, config: NativeNodeConfig, deadline: Duration) -> Result<()> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.start(config, deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = (config, deadline);
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn node_status(&self) -> Result<NodeStatus> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.status(MAX_DEADLINE).map(|status| status.state)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn begin_login(&self, deadline: Duration) -> Result<LoginStatus> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.login(deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = deadline;
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn login_status(&self, deadline: Duration) -> Result<LoginStatus> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.status(deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = deadline;
            Err(Failure::ProviderUnavailable)
        }
    }
    pub(crate) fn stop_node(&self, deadline: Duration) -> Result<()> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.stop(deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = deadline;
            Err(Failure::ProviderUnavailable)
        }
    }
}
impl Backend for TailscaleBackend {
    fn provider(&self) -> Provider {
        Provider::Tailscale
    }
    fn evidence(&self) -> Evidence {
        if cfg!(feature = "tailscale-fixture") {
            Evidence::SyntheticNativeFixture
        } else {
            Evidence::CandidateAbiOnly
        }
    }
    fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.open(host, port, deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = (host, port, deadline);
            Err(Failure::ProviderUnavailable)
        }
    }
    fn read(&self, handle: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.read(handle, max, deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = (handle, max, deadline);
            Err(Failure::ProviderUnavailable)
        }
    }
    fn write(&self, handle: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.write(handle, bytes, deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = (handle, bytes, deadline);
            Err(Failure::ProviderUnavailable)
        }
    }
    fn shutdown_write(&self, handle: u64, deadline: Duration) -> Result<()> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.shutdown(handle, deadline)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = (handle, deadline);
            Err(Failure::ProviderUnavailable)
        }
    }
    fn close(&self, handle: u64) -> Result<()> {
        #[cfg(feature = "linked-tailscale")]
        {
            self.native.close(handle)
        }
        #[cfg(not(feature = "linked-tailscale"))]
        {
            let _ = handle;
            Err(Failure::ProviderUnavailable)
        }
    }
}
/// Link/load probe only: links all used symbols and checks version plus invalid status. Never starts
/// an engine or invokes a store callback.
pub fn verify_managed_abi_presence() -> Result<()> {
    #[cfg(not(feature = "linked-tailscale"))]
    {
        Err(Failure::ProviderUnavailable)
    }
    #[cfg(feature = "linked-tailscale")]
    {
        linked::presence()
    }
}

#[cfg(test)]
mod tests;

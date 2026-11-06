//! Static/dynamic link to the existing Heeler + portable-stream candidate ABI.
//! Managed node entry points own isolated native epochs; legacy linking is
//! retained for ABI experiments. No system TCP or plaintext-storage fallback.
use crate::nodes::{NodeStatus, SecretConfig};
use crate::{Backend, Evidence, Failure, Provider, Result};
#[cfg(feature = "linked-easytier")]
use crate::{MAX_DEADLINE, MAX_IO};
#[cfg(feature = "linked-easytier")]
use std::ffi::{CString, c_char, c_int};
#[cfg(feature = "linked-easytier")]
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

#[cfg(feature = "linked-easytier")]
#[link(name = "heeler_easytier")]
unsafe extern "C" {
    fn heeler_et_node_start(
        config: *const c_char,
        timeout_ms: u32,
        out_node: *mut u64,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_node_status(
        node: u64,
        out_state: *mut u32,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_node_stop(node: u64, timeout_ms: u32, err: *mut c_char, errlen: usize) -> c_int;
    fn heeler_et_node_stream_connect(
        node: u64,
        network: *const c_char,
        host: *const c_char,
        port: u16,
        timeout_ms: u32,
        out_handle: *mut u64,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_stream_connect(
        key: *const c_char,
        network: *const c_char,
        host: *const c_char,
        port: u16,
        timeout_ms: u32,
        out_handle: *mut u64,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_stream_read(
        handle: u64,
        buf: *mut u8,
        len: usize,
        timeout_ms: u32,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_stream_write(
        handle: u64,
        buf: *const u8,
        len: usize,
        timeout_ms: u32,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_stream_shutdown_write(
        handle: u64,
        timeout_ms: u32,
        err: *mut c_char,
        errlen: usize,
    ) -> c_int;
    fn heeler_et_stream_close(handle: u64, err: *mut c_char, errlen: usize) -> c_int;
}

/// The explicit instance key and required network selector are immutable. They
/// are never derived from a destination IP, selected through another profile,
/// or printed through Debug. Node setup remains a separate unimplemented layer.
pub struct EasyTierBackend {
    #[cfg(feature = "linked-easytier")]
    instance_key: Option<CString>,
    #[cfg(feature = "linked-easytier")]
    node: AtomicU64,
    #[cfg(feature = "linked-easytier")]
    network: CString,
}
impl EasyTierBackend {
    /// Legacy key-based ABI experiment. Product node ownership uses
    /// OverlayRuntime::start_easytier_profile and never this constructor.
    pub fn linked(instance_key: &str, network: &str) -> Result<Self> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (instance_key, network);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            if instance_key.is_empty()
                || instance_key.len() > 128
                || instance_key.chars().any(char::is_control)
                || network.is_empty()
                || network.len() > 256
                || network.chars().any(char::is_control)
            {
                return Err(Failure::InvalidRoute);
            }
            Ok(Self {
                instance_key: Some(CString::new(instance_key).map_err(|_| Failure::InvalidRoute)?),
                node: AtomicU64::new(0),
                network: CString::new(network).map_err(|_| Failure::InvalidRoute)?,
            })
        }
    }
    pub(crate) fn managed(network: &str) -> Result<Self> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = network;
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            Ok(Self {
                instance_key: None,
                node: AtomicU64::new(0),
                network: CString::new(network).map_err(|_| Failure::InvalidRoute)?,
            })
        }
    }
    pub(crate) fn start_node(&self, config: &SecretConfig, deadline: Duration) -> Result<()> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (config, deadline);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            if self.instance_key.is_some() || self.node.load(Ordering::Acquire) != 0 {
                return Err(Failure::Busy);
            }
            // Short-lived owned buffer, erased by SecretConfig's Drop after FFI returns.
            let mut bytes = config.bytes().to_vec();
            bytes.push(0);
            let owned = SecretConfig::nul_terminated(bytes);
            let mut node = 0;
            let mut error = [0 as c_char; 512];
            // SAFETY: input and output buffers remain owned until synchronous return.
            let code = unsafe {
                heeler_et_node_start(
                    owned.bytes().as_ptr().cast(),
                    milliseconds(deadline)?,
                    &mut node,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            // A failed start may still own native resources. Preserve its lease.
            self.node.store(node, Ordering::Release);
            if code != 0 {
                Err(Failure::NativeRejected(code))
            } else if node == 0 {
                Err(Failure::InvalidNativeResponse)
            } else {
                Ok(())
            }
        }
    }
    pub(crate) fn node_status(&self) -> Result<NodeStatus> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            let mut state = 0;
            let mut error = [0 as c_char; 512];
            // SAFETY: all output buffers remain valid until the worker returns.
            let code = unsafe {
                heeler_et_node_status(
                    self.node.load(Ordering::Acquire),
                    &mut state,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            if code != 0 {
                return Err(Failure::NativeRejected(code));
            }
            match state {
                0 => Ok(NodeStatus::Starting),
                1 => Ok(NodeStatus::EngineStarted),
                2 => Ok(NodeStatus::Closing),
                _ => Err(Failure::InvalidNativeResponse),
            }
        }
    }
    pub(crate) fn stop_node(&self, deadline: Duration) -> Result<()> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = deadline;
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            let node = self.node.load(Ordering::Acquire);
            if node == 0 {
                return Ok(());
            }
            let mut error = [0 as c_char; 512];
            // SAFETY: this backend exclusively owns the node and its cleanup.
            let code = unsafe {
                heeler_et_node_stop(
                    node,
                    milliseconds(deadline)?,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            if code == 0 {
                self.node.store(0, Ordering::Release);
                Ok(())
            } else {
                Err(Failure::ClosePending)
            }
        }
    }
}

#[cfg(feature = "linked-easytier")]
fn milliseconds(deadline: Duration) -> Result<u32> {
    if deadline.is_zero() || deadline > MAX_DEADLINE {
        return Err(Failure::InvalidDeadline);
    }
    Ok(deadline.as_millis().max(1) as u32)
}

impl Backend for EasyTierBackend {
    fn provider(&self) -> Provider {
        Provider::EasyTier
    }
    fn evidence(&self) -> Evidence {
        if cfg!(feature = "native-fixture") {
            Evidence::SyntheticNativeFixture
        } else {
            Evidence::CandidateAbiOnly
        }
    }
    fn open(&self, host: &str, port: u16, deadline: Duration) -> Result<u64> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (host, port, deadline);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            let host = CString::new(host).map_err(|_| Failure::InvalidRoute)?;
            let mut handle = 0;
            let mut error = [0 as c_char; 512];
            // SAFETY: owned NUL-terminated strings and writable output/error
            // buffers remain live until this synchronous worker call returns.
            let code = unsafe {
                if let Some(key) = &self.instance_key {
                    heeler_et_stream_connect(
                        key.as_ptr(),
                        self.network.as_ptr(),
                        host.as_ptr(),
                        port,
                        milliseconds(deadline)?,
                        &mut handle,
                        error.as_mut_ptr(),
                        error.len(),
                    )
                } else {
                    heeler_et_node_stream_connect(
                        self.node.load(Ordering::Acquire),
                        self.network.as_ptr(),
                        host.as_ptr(),
                        port,
                        milliseconds(deadline)?,
                        &mut handle,
                        error.as_mut_ptr(),
                        error.len(),
                    )
                }
            };
            if code != 0 {
                Err(Failure::NativeRejected(code))
            } else if handle == 0 {
                Err(Failure::InvalidNativeResponse)
            } else {
                Ok(handle)
            }
        }
    }
    fn read(&self, handle: u64, max: usize, deadline: Duration) -> Result<Vec<u8>> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (handle, max, deadline);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            if max == 0 || max > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            let mut bytes = vec![0; max];
            let mut error = [0 as c_char; 512];
            // SAFETY: bytes/error are owned by this worker and valid for the
            // duration of the foreign call, even if its Future was cancelled.
            let count = unsafe {
                heeler_et_stream_read(
                    handle,
                    bytes.as_mut_ptr(),
                    bytes.len(),
                    milliseconds(deadline)?,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            if count < 0 {
                return Err(Failure::NativeRead(count));
            }
            if count as usize > bytes.len() {
                return Err(Failure::InvalidNativeResponse);
            }
            bytes.truncate(count as usize);
            Ok(bytes) // Empty is EOF, never an empty network/profile list.
        }
    }
    fn write(&self, handle: u64, bytes: &[u8], deadline: Duration) -> Result<usize> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (handle, bytes, deadline);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            if bytes.is_empty() || bytes.len() > MAX_IO {
                return Err(Failure::InvalidRoute);
            }
            let mut error = [0 as c_char; 512];
            // SAFETY: bytes remain owned by the worker closure until return.
            let count = unsafe {
                heeler_et_stream_write(
                    handle,
                    bytes.as_ptr(),
                    bytes.len(),
                    milliseconds(deadline)?,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            // Once a write enters the ABI, any error/zero is conservative
            // UNKNOWN, even if native also describes a timeout or closed handle.
            // Positive prefixes are returned once; there is no write_all retry.
            if count <= 0 {
                Err(Failure::UnknownWrite)
            } else if count as usize > bytes.len() {
                Err(Failure::InvalidNativeResponse)
            } else {
                Ok(count as usize)
            }
        }
    }
    fn shutdown_write(&self, handle: u64, deadline: Duration) -> Result<()> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = (handle, deadline);
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            let mut error = [0 as c_char; 512];
            // SAFETY: error buffer outlives the synchronous worker call.
            let code = unsafe {
                heeler_et_stream_shutdown_write(
                    handle,
                    milliseconds(deadline)?,
                    error.as_mut_ptr(),
                    error.len(),
                )
            };
            if code == 0 {
                Ok(())
            } else {
                Err(Failure::UnknownWrite)
            }
        }
    }
    fn close(&self, handle: u64) -> Result<()> {
        #[cfg(not(feature = "linked-easytier"))]
        {
            let _ = handle;
            Err(Failure::ProviderUnavailable)
        }
        #[cfg(feature = "linked-easytier")]
        {
            let mut error = [0 as c_char; 512];
            // SAFETY: this single closing owner keeps the linked native code
            // alive. It holds no read/write/lifecycle mutex across this call.
            let code = unsafe { heeler_et_stream_close(handle, error.as_mut_ptr(), error.len()) };
            if code == 0 || code == -6 {
                Ok(())
            } else {
                Err(Failure::ClosePending)
            }
        }
    }
}

/// Link all additive node symbols and call only status(0). This initializes no
/// node and reads no identity. Source/library verification remains external.
pub fn verify_managed_abi_presence() -> Result<()> {
    #[cfg(not(feature = "linked-easytier"))]
    {
        Err(Failure::ProviderUnavailable)
    }
    #[cfg(feature = "linked-easytier")]
    {
        std::hint::black_box([
            heeler_et_node_start as *const (),
            heeler_et_node_status as *const (),
            heeler_et_node_stop as *const (),
            heeler_et_node_stream_connect as *const (),
        ]);
        let mut state = 0;
        let mut error = [0 as c_char; 128];
        // SAFETY: zero is deliberately invalid; owned output buffers remain live.
        let code = unsafe { heeler_et_node_status(0, &mut state, error.as_mut_ptr(), error.len()) };
        if code == -6 {
            Ok(())
        } else {
            Err(Failure::InvalidNativeResponse)
        }
    }
}

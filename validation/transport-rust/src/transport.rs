//! Explicit byte transport selection. SSH verification and authentication stay
//! in the shared caller; a dialer cannot replace the pinned SSH handler.
use crate::{Cancellation, Result};
use std::{future::Future, pin::Pin};
use tokio::{
    io::{AsyncRead, AsyncWrite},
    net::TcpStream,
};

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum OverlayProvider {
    EasyTier,
    Tailscale,
    ZeroTier,
}

/// Durable route identity, excluding process-local node epochs and owners.
/// A profile revision must change when its network or local identity changes.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OverlayRouteIdentity {
    pub provider: OverlayProvider,
    pub profile_id: String,
    pub profile_revision: u64,
    pub identity_ref: String,
}

pub trait ByteStream: AsyncRead + AsyncWrite + Unpin + Send + 'static {
    /// Retire only this connection's resources. Must never block the executor.
    fn abort(&mut self) {}
    /// Metadata comes from the actual connected stream, not a caller-provided
    /// recovery flag. None is exclusively the legacy/system route semantics.
    fn route_identity(&self) -> Option<OverlayRouteIdentity> {
        None
    }
}
impl ByteStream for TcpStream {}
pub type DialFuture<'a> = Pin<Box<dyn Future<Output = Result<Box<dyn ByteStream>>> + Send + 'a>>;

/// An explicit route for one SSH connection. Implementations must honor
/// cancellation without retrying a write or selecting another transport.
pub trait Dialer: Send + Sync {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> DialFuture<'_>;
}

/// Existing OS TCP/DNS route. Overlay routes never call this implementation.
pub struct SystemDialer;
impl Dialer for SystemDialer {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> DialFuture<'_> {
        Box::pin(async move {
            tokio::select! { biased;
                _ = cancel.wait() => Err("cancelled"),
                stream = TcpStream::connect((host.as_str(), port)) => {
                    Ok(Box::new(stream.map_err(|_| "connection_failed")?) as Box<dyn ByteStream>)
                }
            }
        })
    }
}

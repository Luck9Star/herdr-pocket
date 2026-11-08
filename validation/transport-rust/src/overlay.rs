//! AsyncRead/AsyncWrite over the owned overlay ABI. No socket, DNS, retry loop,
//! blocking wait, or native call occurs on the Tokio/UI executor.
use crate::{
    Cancellation,
    transport::{ByteStream, DialFuture, Dialer, OverlayProvider, OverlayRouteIdentity},
};
use overlay_runtime::{
    Evidence, Failure, MAX_DEADLINE, MAX_IO, Operation, OverlayRuntime, Owner, StreamLease,
    nodes::NodeLease,
};
use std::{
    future::Future,
    io,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    time::Sleep,
};

/// A route is the exact app-owned node epoch, including its immutable profile
/// revision. Reconnection needs a fresh owner; stale revisions never follow a
/// replacement profile. Keep runtime alive to inspect pending cleanup budgets.
pub struct OverlayDialer {
    runtime: Arc<OverlayRuntime>,
    node: NodeLease,
    deadline: Duration,
}
impl OverlayDialer {
    pub fn new(
        runtime: Arc<OverlayRuntime>,
        node: NodeLease,
        deadline: Duration,
    ) -> crate::Result<Self> {
        if deadline.is_zero() || deadline > MAX_DEADLINE {
            return Err("overlay_invalid_deadline");
        }
        require_overlay_evidence(node.evidence())?;
        Ok(Self {
            runtime,
            node,
            deadline,
        })
    }
}

pub(crate) fn require_overlay_evidence(evidence: Evidence) -> crate::Result<()> {
    if evidence == Evidence::SyntheticNativeFixture
        && !cfg!(any(
            feature = "overlay-native-fixture",
            feature = "overlay-tailscale-fixture",
            feature = "overlay-zerotier-fixture"
        ))
    {
        Err("overlay_fixture_disabled")
    } else {
        Ok(())
    }
}

struct PendingOwner {
    runtime: Arc<OverlayRuntime>,
    owner: Owner,
    armed: bool,
}
impl Drop for PendingOwner {
    fn drop(&mut self) {
        if self.armed {
            let _ = self.runtime.cancel_owner(&self.owner);
        }
    }
}
impl Dialer for OverlayDialer {
    fn dial(&self, host: String, port: u16, cancel: Cancellation) -> DialFuture<'_> {
        Box::pin(async move {
            if cancel.is_cancelled() {
                return Err("cancelled");
            }
            if !cfg!(feature = "overlay-native-fixture") {
                self.runtime
                    .require_provider(self.node.profile().provider)
                    .map_err(code)?;
            }
            let owner = self.runtime.new_owner();
            let mut guard = PendingOwner {
                runtime: self.runtime.clone(),
                owner: owner.clone(),
                armed: true,
            };
            let open = self
                .runtime
                .open_node(&owner, &self.node, &host, port, self.deadline)
                .map_err(code)?;
            let lease = tokio::select! { biased;
                _ = cancel.wait() => return Err("cancelled"),
                value = open => value.map_err(code)?,
            };
            // No native handle is leaked if cancellation wins after open ready.
            if cancel.is_cancelled() {
                return Err("cancelled");
            }
            guard.armed = false;
            Ok(Box::new(OverlayStream::new(
                self.runtime.clone(),
                owner,
                lease,
                self.deadline,
                cancel,
                self.node.identity_ref(),
                u64::from(self.node.profile_revision()),
            )) as Box<dyn ByteStream>)
        })
    }
}
fn code(failure: Failure) -> &'static str {
    match failure {
        Failure::ProviderUnavailable => "overlay_provider_unavailable",
        Failure::StaleRevision => "overlay_stale_revision",
        Failure::WrongOwner => "overlay_wrong_owner",
        Failure::Cancelled => "cancelled",
        Failure::UnknownWrite => "overlay_unknown_write",
        _ => "overlay_transport_failed",
    }
}
fn io_error(failure: Failure) -> io::Error {
    let kind = if failure == Failure::UnknownWrite {
        io::ErrorKind::Other
    } else if failure == Failure::Cancelled {
        io::ErrorKind::ConnectionAborted
    } else {
        io::ErrorKind::ConnectionReset
    };
    io::Error::new(kind, code(failure))
}
struct PendingWrite {
    operation: Operation<usize>,
    submitted: Vec<u8>,
}

pub struct OverlayStream {
    runtime: Arc<OverlayRuntime>,
    owner: Owner,
    lease: StreamLease,
    route: OverlayRouteIdentity,
    deadline: Duration,
    cancel: Cancellation,
    read: Option<Operation<Vec<u8>>>,
    read_retry: Option<Pin<Box<Sleep>>>,
    pending_read: Vec<u8>,
    read_offset: usize,
    write: Option<PendingWrite>,
    shutdown: Option<Operation<()>>,
    write_shutdown: bool,
    failed: bool,
    eof: bool,
}
impl OverlayStream {
    fn new(
        runtime: Arc<OverlayRuntime>,
        owner: Owner,
        lease: StreamLease,
        deadline: Duration,
        cancel: Cancellation,
        identity_ref: &str,
        profile_revision: u64,
    ) -> Self {
        let route = OverlayRouteIdentity {
            provider: match lease.profile().provider {
                overlay_runtime::Provider::EasyTier => OverlayProvider::EasyTier,
                overlay_runtime::Provider::Tailscale => OverlayProvider::Tailscale,
                overlay_runtime::Provider::ZeroTier => OverlayProvider::ZeroTier,
            },
            profile_id: lease.profile().id.clone(),
            profile_revision,
            identity_ref: identity_ref.into(),
        };
        Self {
            runtime,
            owner,
            lease,
            route,
            deadline,
            cancel,
            read: None,
            read_retry: None,
            pending_read: Vec::new(),
            read_offset: 0,
            write: None,
            shutdown: None,
            write_shutdown: false,
            failed: false,
            eof: false,
        }
    }
    pub fn profile(&self) -> &overlay_runtime::ProfileKey {
        self.lease.profile()
    }
    pub fn profile_revision(&self) -> u64 {
        self.route.profile_revision
    }
    pub fn evidence(&self) -> Evidence {
        self.lease.evidence()
    }
    /// Initiates asynchronous close; success is not proof that native cleanup
    /// finished. The owning runtime retains failed/pending resources and budget.
    pub fn close(&mut self) {
        if !self.failed {
            self.failed = true;
            let _ = self.runtime.cancel_owner(&self.owner);
        }
        self.read = None;
        self.read_retry = None;
        self.write = None;
        self.shutdown = None;
    }
    fn ready(&mut self, cx: &Context<'_>, write: bool) -> io::Result<()> {
        if self.failed {
            return Err(io::Error::new(
                io::ErrorKind::ConnectionAborted,
                "overlay_closed",
            ));
        }
        if let Err(error) = self.cancel.io_ready(cx, write) {
            self.close();
            return Err(error);
        }
        Ok(())
    }
    fn fail(&mut self, failure: Failure) -> io::Error {
        self.close();
        io_error(failure)
    }
}
impl ByteStream for OverlayStream {
    fn abort(&mut self) {
        self.close();
    }
    fn route_identity(&self) -> Option<OverlayRouteIdentity> {
        Some(self.route.clone())
    }
}
impl Drop for OverlayStream {
    fn drop(&mut self) {
        self.close();
    }
}
impl AsyncRead for OverlayStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if let Err(error) = this.ready(cx, false) {
            return Poll::Ready(Err(error));
        }
        if buf.remaining() == 0 {
            return Poll::Ready(Ok(()));
        }
        if this.read_offset < this.pending_read.len() {
            let count = buf
                .remaining()
                .min(this.pending_read.len() - this.read_offset);
            buf.put_slice(&this.pending_read[this.read_offset..this.read_offset + count]);
            this.read_offset += count;
            if this.read_offset == this.pending_read.len() {
                this.pending_read.clear();
                this.read_offset = 0;
            }
            return Poll::Ready(Ok(()));
        }
        if this.eof {
            return Poll::Ready(Ok(()));
        }
        if let Some(retry) = &mut this.read_retry {
            if retry.as_mut().poll(cx).is_pending() {
                return Poll::Pending;
            }
            this.read_retry = None;
        }
        if this.read.is_none() {
            match this.runtime.read(
                &this.owner,
                &this.lease,
                buf.remaining().min(MAX_IO),
                this.deadline,
            ) {
                Ok(operation) => this.read = Some(operation),
                Err(error) => return Poll::Ready(Err(this.fail(error))),
            }
        }
        match Pin::new(this.read.as_mut().unwrap()).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(value) => {
                this.read = None;
                match value {
                    Err(Failure::ReadTimedOut) => {
                        // The previous native call is already fully returned
                        // and its read slot released. Treat idle as pending,
                        // with a timer even if a faulty backend times out early.
                        let mut retry = Box::pin(tokio::time::sleep(Duration::from_millis(10)));
                        let _ = retry.as_mut().poll(cx);
                        this.read_retry = Some(retry);
                        Poll::Pending
                    }
                    Err(error) => Poll::Ready(Err(this.fail(error))),
                    Ok(bytes) => {
                        if bytes.len() > MAX_IO {
                            return Poll::Ready(Err(this.fail(Failure::InvalidNativeResponse)));
                        }
                        this.eof = bytes.is_empty();
                        let count = buf.remaining().min(bytes.len());
                        buf.put_slice(&bytes[..count]);
                        if count < bytes.len() {
                            this.pending_read = bytes;
                            this.read_offset = count;
                        }
                        Poll::Ready(Ok(()))
                    }
                }
            }
        }
    }
}
impl AsyncWrite for OverlayStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        let this = self.get_mut();
        if let Err(error) = this.ready(cx, true) {
            return Poll::Ready(Err(error));
        }
        if this.write_shutdown || this.shutdown.is_some() {
            return Poll::Ready(Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "overlay_write_shutdown",
            )));
        }
        if this.write.is_none() {
            if buf.is_empty() {
                return Poll::Ready(Ok(0));
            }
            let submitted = buf[..buf.len().min(MAX_IO)].to_vec();
            match this
                .runtime
                .write(&this.owner, &this.lease, submitted.clone(), this.deadline)
            {
                Ok(operation) => {
                    this.write = Some(PendingWrite {
                        operation,
                        submitted,
                    })
                }
                Err(error) => return Poll::Ready(Err(this.fail(error))),
            }
        }
        let pending = this.write.as_mut().unwrap();
        // A cancelled write future may present a different buffer later. Its
        // old native write may already have progressed: never attribute it to
        // the new buffer or replay either one.
        if !buf.starts_with(&pending.submitted) {
            return Poll::Ready(Err(this.fail(Failure::UnknownWrite)));
        }
        match Pin::new(&mut pending.operation).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(value) => {
                let length = this.write.take().unwrap().submitted.len();
                match value {
                    Ok(count) if count > 0 && count <= length => Poll::Ready(Ok(count)),
                    Ok(_) => Poll::Ready(Err(this.fail(Failure::InvalidNativeResponse))),
                    Err(error) => Poll::Ready(Err(this.fail(error))),
                }
            }
        }
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if let Err(error) = this.ready(cx, true) {
            return Poll::Ready(Err(error));
        }
        // Positive write is local queue acceptance. ABI exposes no remote
        // flush primitive; no extra native write is needed or permitted.
        if this.write.is_some() {
            return Poll::Ready(Err(this.fail(Failure::UnknownWrite)));
        }
        Poll::Ready(Ok(()))
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        if let Err(error) = this.ready(cx, true) {
            return Poll::Ready(Err(error));
        }
        if this.write_shutdown {
            return Poll::Ready(Ok(()));
        }
        if this.write.is_some() {
            return Poll::Ready(Err(this.fail(Failure::UnknownWrite)));
        }
        if this.shutdown.is_none() {
            match this
                .runtime
                .shutdown_write(&this.owner, &this.lease, this.deadline)
            {
                Ok(operation) => this.shutdown = Some(operation),
                Err(error) => return Poll::Ready(Err(this.fail(error))),
            }
        }
        match Pin::new(this.shutdown.as_mut().unwrap()).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(value) => {
                this.shutdown = None;
                match value {
                    Ok(()) => {
                        this.write_shutdown = true;
                        Poll::Ready(Ok(()))
                    }
                    Err(error) => Poll::Ready(Err(this.fail(error))),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests;

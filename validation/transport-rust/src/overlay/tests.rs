//! Synthetic adapter tests only. No real nodes, DNS, identity files or remote hosts.
use super::*;
use overlay_runtime::{Backend, ProfileKey, Provider};
use std::{
    collections::VecDeque,
    sync::{
        Condvar, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    task::Waker,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[derive(Default)]
struct Synthetic {
    bytes: Mutex<VecDeque<u8>>,
    writes: Mutex<Vec<Vec<u8>>>,
    closed: AtomicUsize,
    reads: AtomicUsize,
    idle_timeouts: AtomicUsize,
    write_started: AtomicUsize,
    block_write: bool,
    read_gate: (Mutex<bool>, Condvar),
    block_read: bool,
    short: bool,
    unknown: bool,
}
impl Backend for Synthetic {
    fn provider(&self) -> Provider {
        Provider::EasyTier
    }
    fn evidence(&self) -> Evidence {
        Evidence::SyntheticNativeFixture
    }
    fn open(&self, _: &str, _: u16, _: Duration) -> overlay_runtime::Result<u64> {
        Ok(1)
    }
    fn read(&self, _: u64, max: usize, _: Duration) -> overlay_runtime::Result<Vec<u8>> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        if self
            .idle_timeouts
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| n.checked_sub(1))
            .is_ok()
        {
            return Err(Failure::ReadTimedOut);
        }
        if self.block_read {
            let mut released = self.read_gate.0.lock().unwrap();
            while !*released {
                released = self.read_gate.1.wait(released).unwrap();
            }
        }
        let mut bytes = self.bytes.lock().unwrap();
        let count = max.min(bytes.len());
        Ok(bytes.drain(..count).collect())
    }
    fn write(&self, _: u64, bytes: &[u8], _: Duration) -> overlay_runtime::Result<usize> {
        self.write_started.fetch_add(1, Ordering::SeqCst);
        assert!(bytes.len() <= MAX_IO);
        if self.block_write {
            let mut released = self.read_gate.0.lock().unwrap();
            while !*released {
                released = self.read_gate.1.wait(released).unwrap();
            }
        }
        let count = if self.unknown {
            1
        } else if self.short {
            bytes.len().min(2)
        } else {
            bytes.len()
        };
        self.writes.lock().unwrap().push(bytes[..count].to_vec());
        if self.unknown {
            Err(Failure::UnknownWrite)
        } else {
            Ok(count)
        }
    }
    fn shutdown_write(&self, _: u64, _: Duration) -> overlay_runtime::Result<()> {
        Ok(())
    }
    fn close(&self, _: u64) -> overlay_runtime::Result<()> {
        self.closed.fetch_add(1, Ordering::SeqCst);
        *self.read_gate.0.lock().unwrap() = true;
        self.read_gate.1.notify_all();
        Ok(())
    }
}
fn profile(id: &str) -> ProfileKey {
    ProfileKey {
        provider: Provider::EasyTier,
        id: id.into(),
    }
}
async fn synthetic_stream(backend: Arc<Synthetic>) -> (Arc<OverlayRuntime>, OverlayStream) {
    let runtime = Arc::new(OverlayRuntime::new());
    let key = profile("synthetic-only");
    runtime.attach_profile(key.clone(), backend).unwrap();
    let owner = runtime.new_owner();
    let lease = runtime
        .open_revision(
            &owner,
            &key,
            0,
            "synthetic.invalid",
            22,
            Duration::from_secs(2),
        )
        .unwrap()
        .await
        .unwrap();
    let stream = OverlayStream::new(
        runtime.clone(),
        owner,
        lease,
        Duration::from_secs(2),
        Cancellation::default(),
        "synthetic-identity",
    );
    (runtime, stream)
}
async fn until(check: impl Fn() -> bool) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while !check() {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("synthetic worker did not finish");
}
fn waker() -> Waker {
    Waker::noop().clone()
}

#[tokio::test]
async fn short_write_advances_only_each_accepted_prefix_once() {
    let backend = Arc::new(Synthetic {
        short: true,
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    stream.write_all(b"abcdef").await.unwrap();
    stream.flush().await.unwrap();
    stream.shutdown().await.unwrap();
    assert!(stream.write(b"x").await.is_err());
    assert_eq!(
        *backend.writes.lock().unwrap(),
        [b"ab".to_vec(), b"cd".to_vec(), b"ef".to_vec()]
    );
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
    assert_eq!(backend.closed.load(Ordering::SeqCst), 1);
}
#[tokio::test]
async fn unknown_write_is_sticky_and_never_replays() {
    let backend = Arc::new(Synthetic {
        unknown: true,
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    assert!(stream.write_all(b"abcdef").await.is_err());
    assert!(stream.write(b"abcdef").await.is_err());
    assert!(stream.flush().await.is_err());
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
    assert_eq!(*backend.writes.lock().unwrap(), [b"a".to_vec()]);
}
#[tokio::test]
async fn read_keeps_tail_when_next_poll_has_smaller_buffer() {
    let backend = Arc::new(Synthetic {
        block_read: true,
        bytes: Mutex::new(b"abcdef".iter().copied().collect()),
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    let wake = waker();
    let mut cx = Context::from_waker(&wake);
    let mut large = [0u8; 6];
    assert!(
        Pin::new(&mut stream)
            .poll_read(&mut cx, &mut ReadBuf::new(&mut large))
            .is_pending()
    );
    until(|| backend.reads.load(Ordering::SeqCst) == 1).await;
    *backend.read_gate.0.lock().unwrap() = true;
    backend.read_gate.1.notify_all();
    let mut result = Vec::new();
    for _ in 0..3 {
        let mut small = [0u8; 2];
        stream.read_exact(&mut small).await.unwrap();
        result.extend(small);
    }
    assert_eq!(result, b"abcdef");
    assert_eq!(backend.reads.load(Ordering::SeqCst), 1);
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
}
#[tokio::test]
async fn cancellation_wakes_and_closes_pending_read_without_blocking_executor() {
    let backend = Arc::new(Synthetic {
        block_read: true,
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    let cancel = stream.cancel.clone();
    let task = tokio::spawn(async move { stream.read(&mut [0u8; 8]).await.err().unwrap().kind() });
    until(|| backend.reads.load(Ordering::SeqCst) == 1).await;
    cancel.cancel();
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), task)
            .await
            .unwrap()
            .unwrap(),
        io::ErrorKind::ConnectionAborted
    );
    until(|| runtime.reserved_streams() == 0).await;
    assert_eq!(backend.closed.load(Ordering::SeqCst), 1);
}
#[tokio::test]
async fn idle_read_timeouts_yield_without_closing_or_starting_concurrent_reads() {
    let backend = Arc::new(Synthetic {
        idle_timeouts: AtomicUsize::new(2),
        bytes: Mutex::new(b"ok".iter().copied().collect()),
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    let start = tokio::time::Instant::now();
    let mut result = [0; 2];
    stream.read_exact(&mut result).await.unwrap();
    assert_eq!(&result, b"ok");
    assert!(start.elapsed() >= Duration::from_millis(20));
    assert_eq!(backend.reads.load(Ordering::SeqCst), 3);
    assert_eq!(backend.closed.load(Ordering::SeqCst), 0);
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
}

#[tokio::test]
async fn late_native_read_remains_single_until_original_worker_returns() {
    let backend = Arc::new(Synthetic {
        block_read: true,
        bytes: Mutex::new(b"ok".iter().copied().collect()),
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    stream.deadline = Duration::from_millis(5);
    let task = tokio::spawn(async move {
        let mut bytes = [0; 2];
        stream.read_exact(&mut bytes).await.unwrap();
        bytes
    });
    until(|| backend.reads.load(Ordering::SeqCst) == 1).await;
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert_eq!(backend.reads.load(Ordering::SeqCst), 1);
    *backend.read_gate.0.lock().unwrap() = true;
    backend.read_gate.1.notify_all();
    assert_eq!(task.await.unwrap(), *b"ok");
    until(|| runtime.reserved_streams() == 0).await;
}

#[tokio::test]
async fn large_write_is_bounded_without_replaying_accepted_chunks() {
    let backend = Arc::new(Synthetic::default());
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    stream.write_all(&vec![b'x'; MAX_IO * 2 + 5]).await.unwrap();
    let lengths = backend
        .writes
        .lock()
        .unwrap()
        .iter()
        .map(Vec::len)
        .collect::<Vec<_>>();
    assert_eq!(lengths, [MAX_IO, MAX_IO, 5]);
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
}

#[tokio::test]
async fn replacing_pending_write_buffer_returns_unknown_without_new_submission() {
    let backend = Arc::new(Synthetic {
        block_write: true,
        ..Default::default()
    });
    let (runtime, mut stream) = synthetic_stream(backend.clone()).await;
    let wake = waker();
    let mut cx = Context::from_waker(&wake);
    assert!(
        Pin::new(&mut stream)
            .poll_write(&mut cx, b"original")
            .is_pending()
    );
    until(|| backend.write_started.load(Ordering::SeqCst) == 1).await;
    assert!(matches!(
        Pin::new(&mut stream).poll_write(&mut cx, b"replacement"),
        Poll::Ready(Err(_))
    ));
    drop(stream);
    until(|| runtime.reserved_streams() == 0).await;
    assert_eq!(backend.write_started.load(Ordering::SeqCst), 1);
    assert_eq!(backend.writes.lock().unwrap().len(), 1);
}
#[tokio::test]
async fn owner_and_profile_do_not_cross_even_for_same_virtual_destination() {
    let runtime = Arc::new(OverlayRuntime::new());
    let a = Arc::new(Synthetic::default());
    let b = Arc::new(Synthetic::default());
    runtime.attach_profile(profile("a"), a.clone()).unwrap();
    runtime.attach_profile(profile("b"), b.clone()).unwrap();
    let owner_a = runtime.new_owner();
    let owner_b = runtime.new_owner();
    let lease_a = runtime
        .open_revision(
            &owner_a,
            &profile("a"),
            0,
            "same.invalid",
            22,
            Duration::from_secs(2),
        )
        .unwrap()
        .await
        .unwrap();
    let lease_b = runtime
        .open_revision(
            &owner_b,
            &profile("b"),
            0,
            "same.invalid",
            22,
            Duration::from_secs(2),
        )
        .unwrap()
        .await
        .unwrap();
    assert!(matches!(
        runtime.write(&owner_b, &lease_a, b"x".to_vec(), Duration::from_secs(2)),
        Err(Failure::WrongOwner)
    ));
    let mut stream_a = OverlayStream::new(
        runtime.clone(),
        owner_a,
        lease_a,
        Duration::from_secs(2),
        Cancellation::default(),
        "synthetic-identity",
    );
    let mut stream_b = OverlayStream::new(
        runtime.clone(),
        owner_b,
        lease_b,
        Duration::from_secs(2),
        Cancellation::default(),
        "synthetic-identity",
    );
    stream_a.write_all(b"a").await.unwrap();
    stream_a.close();
    stream_b.write_all(b"b").await.unwrap();
    assert_eq!(*a.writes.lock().unwrap(), [b"a".to_vec()]);
    assert_eq!(*b.writes.lock().unwrap(), [b"b".to_vec()]);
    drop(stream_b);
    until(|| runtime.reserved_streams() == 0).await;
}

#[cfg(feature = "overlay-native-fixture")]
mod native {
    use super::*;
    use overlay_runtime::nodes::{NodeSpec, SecretConfig, SecureConfigSource};
    unsafe extern "C" {
        fn fixture_control(operation: i32);
        fn fixture_metric(metric: i32) -> i32;
    }
    struct Source;
    impl SecureConfigSource for Source {
        fn load(&self, _: &NodeSpec) -> overlay_runtime::Result<SecretConfig> {
            SecretConfig::from_bytes(b"synthetic-network".to_vec())
        }
    }
    #[tokio::test]
    async fn managed_route_cancelled_late_open_and_foreign_runtime_are_isolated() {
        let runtime = Arc::new(OverlayRuntime::new());
        let key = profile("managed-fixture");
        let node = runtime
            .start_easytier_profile(
                NodeSpec {
                    profile: key.clone(),
                    revision: 7,
                    network: "synthetic-network".into(),
                    identity_ref: "fixture-only".into(),
                },
                Some(Arc::new(Source)),
                Duration::from_secs(2),
            )
            .unwrap()
            .await
            .unwrap();
        let other = Arc::new(OverlayRuntime::new());
        let wrong =
            OverlayDialer::new(other.clone(), node.clone(), Duration::from_secs(2)).unwrap();
        assert_eq!(
            wrong
                .dial("same.invalid".into(), 22, Cancellation::default())
                .await
                .err(),
            Some("overlay_wrong_owner")
        );
        let route = Arc::new(
            OverlayDialer::new(runtime.clone(), node.clone(), Duration::from_secs(2)).unwrap(),
        );
        let cancel = Cancellation::default();
        let c = cancel.clone();
        let task = tokio::spawn(async move { route.dial("late".into(), 22, c).await.err() });
        until(|| unsafe { fixture_metric(1) } >= 1).await;
        cancel.cancel();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(1), task)
                .await
                .unwrap()
                .unwrap(),
            Some("cancelled")
        );
        assert_eq!(runtime.reserved_streams(), 1);
        unsafe { fixture_control(1) };
        until(|| runtime.reserved_streams() == 0).await;
        assert_eq!(unsafe { fixture_metric(4) }, 1);
        runtime.detach_profile(&key).unwrap();
        let route =
            OverlayDialer::new(runtime.clone(), node.clone(), Duration::from_secs(2)).unwrap();
        assert!(
            route
                .dial("same.invalid".into(), 22, Cancellation::default())
                .await
                .is_err()
        );
        runtime
            .stop_node(&node, Duration::from_secs(2))
            .unwrap()
            .await
            .unwrap();
        assert_eq!(other.reserved_streams(), 0);
    }
}

#[cfg(unix)]
mod ssh;

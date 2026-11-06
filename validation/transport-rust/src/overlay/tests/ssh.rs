//! Real SSH key exchange over a synthetic Unix socketpair backend, through
//! OverlayStream. It does not bind TCP, resolve DNS, or load any user identity.
use super::*;
use crate::{
    Audit, InputHooks, RemoteConfig, observe_interactive_with_dialer, read_once_with_dialer,
    transport::DialFuture,
};
use russh::{
    keys::{PrivateKey, ssh_key::private::Ed25519Keypair},
    server,
};
use std::{
    io::{Read, Write},
    os::unix::net::UnixStream as NativeStream,
};

struct SocketPairBackend {
    reader: Mutex<NativeStream>,
    writer: Mutex<NativeStream>,
    closer: NativeStream,
}
impl Backend for SocketPairBackend {
    fn provider(&self) -> Provider {
        Provider::EasyTier
    }
    fn evidence(&self) -> Evidence {
        Evidence::SyntheticNativeFixture
    }
    fn open(&self, host: &str, port: u16, _: Duration) -> overlay_runtime::Result<u64> {
        assert_eq!(host, "synthetic-overlay.invalid");
        assert_eq!(port, 22);
        Ok(1)
    }
    fn read(&self, _: u64, max: usize, _: Duration) -> overlay_runtime::Result<Vec<u8>> {
        let mut bytes = vec![0; max];
        let count = self
            .reader
            .lock()
            .unwrap()
            .read(&mut bytes)
            .map_err(|_| Failure::NativeRead(-1))?;
        bytes.truncate(count);
        Ok(bytes)
    }
    fn write(&self, _: u64, bytes: &[u8], _: Duration) -> overlay_runtime::Result<usize> {
        self.writer
            .lock()
            .unwrap()
            .write(&bytes[..bytes.len().min(512)])
            .map_err(|_| Failure::UnknownWrite)
    }
    fn shutdown_write(&self, _: u64, _: Duration) -> overlay_runtime::Result<()> {
        self.closer
            .shutdown(std::net::Shutdown::Write)
            .map_err(|_| Failure::UnknownWrite)
    }
    fn close(&self, _: u64) -> overlay_runtime::Result<()> {
        match self.closer.shutdown(std::net::Shutdown::Both) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == io::ErrorKind::NotConnected => Ok(()),
            Err(_) => Err(Failure::ClosePending),
        }
    }
}
struct OnceDialer(Mutex<Option<OverlayStream>>);
impl Dialer for OnceDialer {
    fn dial(&self, host: String, port: u16, _: Cancellation) -> DialFuture<'_> {
        assert_eq!(host, "synthetic-overlay.invalid");
        assert_eq!(port, 22);
        let stream = self.0.lock().unwrap().take();
        Box::pin(
            async move { Ok(Box::new(stream.ok_or("fixture_consumed")?) as Box<dyn ByteStream>) },
        )
    }
}
struct RejectAuth(Arc<AtomicUsize>);
impl server::Handler for RejectAuth {
    type Error = russh::Error;
    async fn auth_publickey(
        &mut self,
        _: &str,
        _: server::VerifiedPublicKey<'_>,
    ) -> std::result::Result<server::Auth, Self::Error> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(server::Auth::reject())
    }
}
fn key(seed: u8) -> PrivateKey {
    PrivateKey::new(Ed25519Keypair::from_seed(&[seed; 32]).into(), "").unwrap()
}

#[tokio::test]
async fn readonly_and_guarded_routes_reject_wrong_hostkey_before_auth() {
    for guarded in [false, true] {
        let (native, peer) = NativeStream::pair().unwrap();
        native
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        native
            .set_write_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        peer.set_nonblocking(true).unwrap();
        let peer = tokio::net::UnixStream::from_std(peer).unwrap();
        let backend = Arc::new(SocketPairBackend {
            reader: Mutex::new(native.try_clone().unwrap()),
            writer: Mutex::new(native.try_clone().unwrap()),
            closer: native,
        });
        let runtime = Arc::new(OverlayRuntime::new());
        let owner = runtime.new_owner();
        let profile = profile("synthetic-ssh");
        runtime.attach_profile(profile.clone(), backend).unwrap();
        let lease = runtime
            .open_revision(
                &owner,
                &profile,
                0,
                "synthetic-overlay.invalid",
                22,
                Duration::from_secs(2),
            )
            .unwrap()
            .await
            .unwrap();
        let cancel = Cancellation::default();
        let dialer = OnceDialer(Mutex::new(Some(OverlayStream::new(
            runtime.clone(),
            owner,
            lease,
            Duration::from_secs(2),
            cancel.clone(),
            "synthetic-identity",
        ))));
        let server_key = key(1);
        let client_key = key(2);
        let wrong_key = key(3);
        let attempts = Arc::new(AtomicUsize::new(0));
        let auth = attempts.clone();
        let server = tokio::spawn(async move {
            let config = Arc::new(server::Config {
                keys: vec![server_key],
                ..Default::default()
            });
            if let Ok(session) = server::run_stream(config, peer, RejectAuth(auth)).await {
                let _ = session.await;
            }
        });
        let config = RemoteConfig {
            schema_version: 1,
            host: "synthetic-overlay.invalid".into(),
            port: 22,
            username: "fixture".into(),
            expected_host_key: wrong_key.public_key().to_openssh().unwrap(),
            private_key_pem: client_key
                .to_openssh(russh::keys::ssh_key::LineEnding::LF)
                .unwrap()
                .to_string(),
            socket_path: "/tmp/herdr/sessions/fixture/herdr.sock".into(),
            herdr_path: "/fixture/herdr".into(),
            session: "fixture".into(),
            pane_id: "w1:p1".into(),
            review_confirmed: true,
        };
        let audit = Arc::new(Audit::default());
        let error = if guarded {
            observe_interactive_with_dialer(
                config,
                None,
                cancel,
                audit.clone(),
                |_| {},
                |_| async { Ok("w1:p1".into()) },
                |_| async { Ok(()) },
                InputHooks {
                    recovery: crate::recovery::Recovery::disabled(),
                    ready: Arc::new(|_| panic!("wrong host key exposed input")),
                },
                &dialer,
            )
            .await
            .err()
        } else {
            read_once_with_dialer(config, cancel, audit.clone(), |_| {}, &dialer)
                .await
                .err()
        };
        assert_eq!(error, Some("host_key_mismatch"));
        assert!(audit.snapshot().host_key_checked);
        assert!(!audit.snapshot().host_key_matched);
        assert!(!audit.snapshot().auth_started);
        assert_eq!(attempts.load(Ordering::SeqCst), 0);
        until(|| runtime.reserved_streams() == 0).await;
        tokio::time::timeout(Duration::from_secs(3), server)
            .await
            .unwrap()
            .unwrap();
    }
}

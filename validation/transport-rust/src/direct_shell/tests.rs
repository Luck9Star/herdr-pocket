//! A temporary loopback SSH server connected to a real /bin/sh PTY. No user keys,
//! authorization files, login shell configuration, or external hosts are read.
use super::*;
use russh::server::Server as _;
use russh::{Channel, ChannelId, server};
use std::{
    fs::File,
    os::fd::{AsRawFd, FromRawFd},
    os::unix::process::CommandExt,
    path::PathBuf,
    process::{Child, Command as Process, Stdio},
    sync::atomic::AtomicUsize,
};
use tokio::io::unix::AsyncFd;

struct Temp(PathBuf);
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[derive(Default)]
struct Facts {
    active: AtomicUsize,
    auth: AtomicUsize,
    shells: AtomicUsize,
    sizes: Mutex<Vec<(u32, u32)>>,
}
struct Factory {
    key: PublicKey,
    facts: Arc<Facts>,
    cwd: PathBuf,
    reject: &'static str,
}
struct Peer {
    key: PublicKey,
    facts: Arc<Facts>,
    cwd: PathBuf,
    reject: &'static str,
    master: Option<Arc<AsyncFd<File>>>,
    slave: Option<File>,
    child: Arc<Mutex<Option<Child>>>,
    stop: Cancellation,
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.stop.cancel();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        self.facts.active.fetch_sub(1, Ordering::SeqCst);
    }
}
impl server::Server for Factory {
    type Handler = Peer;
    fn new_client(&mut self, _: Option<std::net::SocketAddr>) -> Peer {
        self.facts.active.fetch_add(1, Ordering::SeqCst);
        Peer {
            key: self.key.clone(),
            facts: self.facts.clone(),
            cwd: self.cwd.clone(),
            reject: self.reject,
            master: None,
            slave: None,
            child: Arc::new(Mutex::new(None)),
            stop: Cancellation::default(),
        }
    }
}
async fn pty_read(fd: &AsyncFd<File>, bytes: &mut [u8]) -> std::io::Result<usize> {
    loop {
        let mut ready = fd.readable().await?;
        match ready.try_io(|f| {
            let len = unsafe { libc::read(f.as_raw_fd(), bytes.as_mut_ptr().cast(), bytes.len()) };
            if len < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(len as usize)
            }
        }) {
            Ok(result) => return result,
            Err(_) => continue,
        }
    }
}
async fn pty_write(fd: &AsyncFd<File>, mut bytes: &[u8]) -> std::io::Result<()> {
    while !bytes.is_empty() {
        let mut ready = fd.writable().await?;
        match ready.try_io(|f| {
            let len = unsafe { libc::write(f.as_raw_fd(), bytes.as_ptr().cast(), bytes.len()) };
            if len < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(len as usize)
            }
        }) {
            Ok(result) => bytes = &bytes[result?..],
            Err(_) => continue,
        }
    }
    Ok(())
}
impl server::Handler for Peer {
    type Error = russh::Error;
    async fn auth_publickey(
        &mut self,
        user: &str,
        key: server::VerifiedPublicKey<'_>,
    ) -> std::result::Result<server::Auth, Self::Error> {
        self.facts.auth.fetch_add(1, Ordering::SeqCst);
        Ok(
            if user == "fixture" && key.public_key.key_data() == self.key.key_data() {
                server::Auth::Accept
            } else {
                server::Auth::reject()
            },
        )
    }
    async fn auth_password(
        &mut self,
        user: &str,
        password: &str,
    ) -> std::result::Result<server::Auth, Self::Error> {
        self.facts.auth.fetch_add(1, Ordering::SeqCst);
        if self.reject == "auth-hang" {
            tokio::time::sleep(Duration::from_millis(400)).await;
        }
        Ok(
            if user == "fixture" && password == "fixture-one-time-password" {
                server::Auth::Accept
            } else {
                server::Auth::reject()
            },
        )
    }
    async fn channel_open_session(
        &mut self,
        _: Channel<server::Msg>,
        reply: server::ChannelOpenHandle,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        reply.accept().await;
        Ok(())
    }
    async fn pty_request(
        &mut self,
        id: ChannelId,
        term: &str,
        cols: u32,
        rows: u32,
        _: u32,
        _: u32,
        _: &[(russh::Pty, u32)],
        session: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        assert_eq!(term, "xterm-256color");
        self.facts.sizes.lock().unwrap().push((cols, rows));
        if self.reject == "pty" {
            session.channel_failure(id)?;
            return Ok(());
        }
        let mut master = -1;
        let mut slave = -1;
        let mut size = libc::winsize {
            ws_col: cols as u16,
            ws_row: rows as u16,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        assert_eq!(
            unsafe {
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    &mut size,
                )
            },
            0
        );
        let master = unsafe { File::from_raw_fd(master) };
        let flags = unsafe { libc::fcntl(master.as_raw_fd(), libc::F_GETFL) };
        assert_eq!(
            unsafe { libc::fcntl(master.as_raw_fd(), libc::F_SETFL, flags | libc::O_NONBLOCK) },
            0
        );
        // The owned File stays registered until AsyncFd is dropped.
        self.master = Some(Arc::new(unsafe { AsyncFd::register(master) }.unwrap()));
        self.slave = Some(unsafe { File::from_raw_fd(slave) });
        session.channel_success(id)?;
        Ok(())
    }
    async fn shell_request(
        &mut self,
        id: ChannelId,
        session: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        if self.reject == "shell" {
            session.channel_failure(id)?;
            return Ok(());
        }
        self.facts.shells.fetch_add(1, Ordering::SeqCst);
        let slave = self.slave.take().unwrap();
        let mut command = Process::new("/bin/sh");
        command
            .arg("-i")
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", &self.cwd)
            .env("TERM", "xterm-256color")
            .current_dir(&self.cwd)
            .stdin(Stdio::from(slave.try_clone().unwrap()))
            .stdout(Stdio::from(slave.try_clone().unwrap()))
            .stderr(Stdio::from(slave));
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() < 0 || libc::ioctl(0, libc::TIOCSCTTY as _, 0) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        *self.child.lock().unwrap() = Some(command.spawn().unwrap());
        session.channel_success(id)?;
        let fd = self.master.clone().unwrap();
        let stop = self.stop.clone();
        let child = self.child.clone();
        let handle = session.handle();
        tokio::spawn(async move {
            let mut bytes = [0u8; 4096];
            loop {
                let n = tokio::select! { biased; _=stop.wait()=>return, result=pty_read(&fd,&mut bytes)=>match result {Ok(n)=>n,Err(_)=>0} };
                if n == 0 {
                    break;
                }
                if handle.data(id, bytes[..n].to_vec()).await.is_err() {
                    return;
                }
            }
            let status = child
                .lock()
                .unwrap()
                .as_mut()
                .and_then(|c| c.wait().ok())
                .and_then(|s| s.code())
                .unwrap_or(255) as u32;
            let _ = handle.exit_status_request(id, status).await;
            let _ = handle.eof(id).await;
            let _ = handle.close(id).await;
        });
        Ok(())
    }
    async fn data(
        &mut self,
        _: ChannelId,
        bytes: &[u8],
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        pty_write(self.master.as_ref().unwrap(), bytes)
            .await
            .unwrap();
        Ok(())
    }
    async fn window_change_request(
        &mut self,
        _: ChannelId,
        cols: u32,
        rows: u32,
        _: u32,
        _: u32,
        _: &mut server::Session,
    ) -> std::result::Result<(), Self::Error> {
        self.facts.sizes.lock().unwrap().push((cols, rows));
        let size = libc::winsize {
            ws_col: cols as u16,
            ws_row: rows as u16,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        assert_eq!(
            unsafe {
                libc::ioctl(
                    self.master.as_ref().unwrap().as_raw_fd(),
                    libc::TIOCSWINSZ as _,
                    &size,
                )
            },
            0
        );
        Ok(())
    }
}
struct Fixture {
    _temp: Temp,
    pem: String,
    pin: String,
    port: u16,
    facts: Arc<Facts>,
    server: tokio::task::JoinHandle<()>,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.pem.zeroize();
        self.server.abort();
    }
}
impl Fixture {
    async fn start(reject: &'static str) -> Self {
        use ring::rand::SecureRandom;
        let mut nonce = [0u8; 16];
        ring::rand::SystemRandom::new().fill(&mut nonce).unwrap();
        let temp = Temp(std::env::temp_dir().join(format!(
            "pocket-shell-{}",
            nonce.iter().map(|n| format!("{n:02x}")).collect::<String>()
        )));
        std::fs::create_dir(&temp.0).unwrap();
        let key_path = temp.0.join("key");
        assert!(
            Process::new("ssh-keygen")
                .args(["-q", "-t", "ed25519", "-N", "", "-f"])
                .arg(&key_path)
                .status()
                .unwrap()
                .success()
        );
        let pem = std::fs::read_to_string(key_path).unwrap();
        let key = decode_secret_key(&pem, None).unwrap();
        let public = key.public_key().clone();
        let pin = public
            .to_openssh()
            .unwrap()
            .split_whitespace()
            .take(2)
            .collect::<Vec<_>>()
            .join(" ");
        let config = Arc::new(server::Config {
            keys: vec![key],
            auth_rejection_time: Duration::ZERO,
            auth_rejection_time_initial: Some(Duration::ZERO),
            ..Default::default()
        });
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let facts = Arc::new(Facts::default());
        let mut factory = Factory {
            key: public,
            facts: facts.clone(),
            cwd: temp.0.clone(),
            reject,
        };
        let server = tokio::spawn(async move {
            factory.run_on_socket(config, &listener).await.unwrap();
        });
        Self {
            _temp: temp,
            pem,
            pin,
            port,
            facts,
            server,
        }
    }
    fn config(&self, password: bool) -> ShellConfig {
        ShellConfig {
            host: "127.0.0.1".into(),
            port: self.port,
            username: "fixture".into(),
            expected_host_key: self.pin.clone(),
            review_confirmed: true,
            cols: 80,
            rows: 24,
            password: password.then(|| "fixture-one-time-password".into()),
            private_key_pem: (!password).then(|| self.pem.clone()),
            private_key_passphrase: None,
        }
    }
    async fn cleaned(&self) {
        timeout(Duration::from_secs(3), async {
            while self.facts.active.load(Ordering::SeqCst) != 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("SSH connections and PTY children retired");
    }
}
struct OpenShell {
    control: ShellControl,
    events: mpsc::UnboundedReceiver<ShellEvent>,
    task: tokio::task::JoinHandle<Result<()>>,
    previous: u64,
}
impl OpenShell {
    fn start(config: ShellConfig) -> Self {
        Self::start_with_ack(config, true)
    }
    fn start_with_ack(config: ShellConfig, acknowledge: bool) -> Self {
        let (control, commands) = shell_commands();
        let (tx, events) = mpsc::unbounded_channel();
        let input = control.clone();
        let task = tokio::spawn(run_shell(config, commands, move |e| {
            let seq = e.seq;
            let data = e.kind == "data";
            tx.send(e).map_err(|_| "cancelled")?;
            if acknowledge && data {
                input.acknowledge(seq)?;
            }
            Ok(())
        }));
        Self {
            control,
            events,
            task,
            previous: 0,
        }
    }
    async fn event(&mut self) -> ShellEvent {
        let event = timeout(Duration::from_secs(5), self.events.recv())
            .await
            .unwrap()
            .expect("shell event");
        assert_eq!(event.seq, self.previous + 1);
        self.previous = event.seq;
        event
    }
    async fn ready(&mut self) {
        assert_eq!(self.event().await.kind, "ready");
    }
    async fn until(&mut self, needle: &str) -> String {
        let mut output = String::new();
        while !output.contains(needle) {
            let event = self.event().await;
            assert_eq!(event.kind, "data");
            output.push_str(&String::from_utf8_lossy(&event.data.unwrap()));
        }
        output
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn standard_shell_real_pty_password_and_key_bidirectional_resize_exit_and_isolation() {
    let fixture = Fixture::start("").await;
    let probe = probe_host_key("127.0.0.1".into(), fixture.port)
        .await
        .unwrap();
    assert_eq!(probe.public_key, fixture.pin);
    assert!(probe.fingerprint.starts_with("SHA256:"));
    assert_eq!(
        fixture.facts.auth.load(Ordering::SeqCst),
        0,
        "probe never authenticates"
    );
    let mut key = OpenShell::start(fixture.config(false));
    let mut password = OpenShell::start(fixture.config(true));
    assert_eq!(
        key.control.write(b"bad-before-ready".to_vec()).await,
        Err("shell_not_ready")
    );
    key.ready().await;
    password.ready().await;
    key.control
        .write(b"printf '\\033[31mkey-output\\033[0m\\n'; stty size\n".to_vec())
        .await
        .unwrap();
    let output = key.until("24 80").await;
    assert!(output.contains("\x1b[31mkey-output\x1b[0m"));
    assert!(!output.contains("password-output"));
    password
        .control
        .write(b"printf 'password-output\\n'\n".to_vec())
        .await
        .unwrap();
    let output = password.until("password-output\r\n").await;
    assert!(!output.contains("key-output"));
    key.control.resize(117, 37).await.unwrap();
    key.control.write(b"stty size\n".to_vec()).await.unwrap();
    assert!(key.until("37 117").await.contains("37 117"));
    assert!(fixture.facts.sizes.lock().unwrap().contains(&(117, 37)));
    key.control.write(b"exit 7\n".to_vec()).await.unwrap();
    loop {
        let e = key.event().await;
        if e.kind == "exit" {
            assert_eq!(e.exit_status, Some(7));
            break;
        }
    }
    assert_eq!(key.task.await.unwrap(), Ok(()));
    password.control.close();
    assert_eq!(password.task.await.unwrap(), Err("cancelled"));
    fixture.cleaned().await;
    assert_eq!(
        password.control.write(b"late".to_vec()).await,
        Err("cancelled")
    );
    assert_eq!(fixture.facts.shells.load(Ordering::SeqCst), 2);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pin_and_auth_failures_and_denied_pty_shell_clean_connections() {
    let fixture = Fixture::start("").await;
    let other = Fixture::start("").await;
    let mut config = fixture.config(true);
    config.expected_host_key = other.pin.clone();
    let shell = OpenShell::start(config);
    assert_eq!(shell.task.await.unwrap(), Err("host_key_mismatch"));
    assert_eq!(fixture.facts.auth.load(Ordering::SeqCst), 0);
    let mut config = fixture.config(true);
    config.password = Some("wrong-synthetic-password".into());
    let shell = OpenShell::start(config);
    assert_eq!(shell.task.await.unwrap(), Err("authentication_failed"));
    fixture.cleaned().await;
    for (reject, error) in [("pty", "pty_failed"), ("shell", "shell_failed")] {
        let fixture = Fixture::start(reject).await;
        let shell = OpenShell::start(fixture.config(true));
        assert_eq!(shell.task.await.unwrap(), Err(error));
        fixture.cleaned().await;
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_interrupts_pending_handshake_authentication_and_active_shell() {
    // A bound loopback peer accepts TCP and intentionally sends no SSH banner.
    let fixture = Fixture::start("").await;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = fixture.config(true);
    config.port = listener.local_addr().unwrap().port();
    let mut shell = OpenShell::start(config);
    let (mut peer, _) = timeout(Duration::from_secs(2), listener.accept())
        .await
        .unwrap()
        .unwrap();
    shell.control.close();
    assert_eq!(
        timeout(Duration::from_secs(1), &mut shell.task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    let mut bytes = Vec::new();
    timeout(Duration::from_secs(1), peer.read_to_end(&mut bytes))
        .await
        .unwrap()
        .unwrap();
    let fixture = Fixture::start("auth-hang").await;
    let mut shell = OpenShell::start(fixture.config(true));
    timeout(Duration::from_secs(3), async {
        while fixture.facts.auth.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    shell.control.close();
    assert_eq!(
        timeout(Duration::from_secs(1), &mut shell.task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    fixture.cleaned().await;
    let fixture = Fixture::start("").await;
    let mut shell = OpenShell::start(fixture.config(true));
    shell.ready().await;
    shell.control.close();
    assert_eq!(
        timeout(Duration::from_secs(1), &mut shell.task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    fixture.cleaned().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_output_ack_bounds_delivery_and_close_interrupts_pending_ack() {
    let fixture = Fixture::start("").await;
    let mut shell = OpenShell::start_with_ack(fixture.config(true), false);
    shell.ready().await;
    let event = timeout(Duration::from_secs(2), shell.events.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(event.kind, "data");
    let input = shell.control.clone();
    let write =
        tokio::spawn(async move { input.write(b"printf 'flow-control\\n'\n".to_vec()).await });
    tokio::time::sleep(Duration::from_millis(30)).await;
    assert!(
        !write.is_finished(),
        "input stays bounded while output waits for render receipt"
    );
    assert_eq!(shell.control.acknowledge(event.seq + 1), Err("stale_ack"));
    shell.control.acknowledge(event.seq).unwrap();
    assert_eq!(
        timeout(Duration::from_secs(2), write)
            .await
            .unwrap()
            .unwrap(),
        Ok(())
    );
    let event = timeout(Duration::from_secs(2), shell.events.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(event.kind, "data");
    shell.control.close();
    assert_eq!(
        timeout(Duration::from_secs(1), shell.task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    fixture.cleaned().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn input_receipt_timeout_retires_queued_input_and_connection() {
    let fixture = Fixture::start("").await;
    let mut shell = OpenShell::start_with_ack(fixture.config(true), false);
    shell.ready().await;
    let event = timeout(Duration::from_secs(2), shell.events.recv())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(event.kind, "data");
    // The unrendered prompt holds output credit; this write must stay queued.
    assert_eq!(
        shell.control.write(b"must-never-run\n".to_vec()).await,
        Err("input_unknown")
    );
    assert_eq!(shell.control.acknowledge(event.seq), Err("cancelled"));
    assert_eq!(
        timeout(Duration::from_secs(1), shell.task)
            .await
            .unwrap()
            .unwrap(),
        Err("cancelled")
    );
    fixture.cleaned().await;
}

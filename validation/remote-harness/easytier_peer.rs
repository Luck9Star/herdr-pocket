//! Copied only into the pinned, temporary Heeler crate's examples directory.
//! The peer bridges one userspace virtual TCP port to a loopback SSH server.
//! It is fixture infrastructure, not a product provider or native API change.
use easytier::common::config::{ConfigLoader, TomlConfigLoader};
use easytier::instance::factory::create_native_instance;
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};
struct Active(Arc<AtomicUsize>);
impl Drop for Active {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 4 {
        std::process::exit(2);
    }
    let config = std::fs::read_to_string(&args[1]).expect("controlled peer config");
    let control = PathBuf::from(&args[2]);
    let stage = |value: &str| {
        std::fs::write(control.join("peer-stage"), value).expect("controlled peer stage")
    };
    let ssh_port: u16 = args[3]
        .to_string_lossy()
        .parse()
        .expect("controlled SSH port");
    let executor = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("controlled peer executor");
    let passed = executor.block_on(async {
        stage("parse-config");
        let Ok(config) = TomlConfigLoader::new_from_str(&config) else {
            return false;
        };
        // Refuse a fixture config that could reach any external discovery host.
        if config.get_stun_servers() != Some(vec![])
            || config.get_tcp_stun_servers() != Some(vec![])
            || config.get_stun_servers_v6() != Some(vec![])
        {
            return false;
        }
        stage("create-instance");
        let Ok(instance) = create_native_instance(config) else {
            return false;
        };
        stage("start-instance");
        if !matches!(
            tokio::time::timeout(Duration::from_secs(8), instance.start()).await,
            Ok(Ok(()))
        ) {
            let _ = tokio::time::timeout(Duration::from_secs(5), instance.stop()).await;
            return false;
        }
        stage("bind-virtual-tcp");
        let Ok(mut listener) = instance
            .data_plane_tcp_bind(0, Duration::from_secs(5))
            .await
        else {
            let _ = tokio::time::timeout(Duration::from_secs(5), instance.stop()).await;
            return false;
        };
        let virtual_port = listener.local_addr().port();
        let accepted = Arc::new(AtomicUsize::new(0));
        let connected = Arc::new(AtomicUsize::new(0));
        let active = Arc::new(AtomicUsize::new(0));
        let (accepted_task, connected_task, active_task) =
            (accepted.clone(), connected.clone(), active.clone());
        let bridges = tokio::spawn(async move {
            let mut tasks = tokio::task::JoinSet::new();
            while let Ok((mut stream, _)) = listener.accept().await {
                accepted_task.fetch_add(1, Ordering::SeqCst);
                active_task.fetch_add(1, Ordering::SeqCst);
                let guard = Active(active_task.clone());
                let connected = connected_task.clone();
                tasks.spawn(async move {
                    let _guard = guard;
                    // Only this server fixture may dial its loopback SSH server.
                    if let Ok(mut host) =
                        tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, ssh_port))
                            .await
                    {
                        connected.fetch_add(1, Ordering::SeqCst);
                        let _ = tokio::io::copy_bidirectional(&mut stream, &mut host).await;
                    }
                });
                while tasks.try_join_next().is_some() {}
            }
            tasks.shutdown().await;
        });
        stage("accepting");
        std::fs::write(
            control.join("peer-ready.tmp"),
            serde_json::to_vec(&serde_json::json!({"virtualTcpPort": virtual_port})).unwrap(),
        )
        .expect("controlled ready file");
        std::fs::rename(control.join("peer-ready.tmp"), control.join("peer-ready"))
            .expect("controlled atomic ready");
        let until = Instant::now() + Duration::from_secs(240);
        while !control.join("stop-peer").exists() && Instant::now() < until {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        stage("stop-instance");
        if tokio::time::timeout(Duration::from_secs(5), instance.stop())
            .await
            .is_err()
        {
            return false;
        }
        stage("drain-bridges");
        bridges.abort();
        let _ = bridges.await;
        let until = Instant::now() + Duration::from_secs(5);
        while active.load(Ordering::SeqCst) != 0 && Instant::now() < until {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        if active.load(Ordering::SeqCst) != 0 {
            return false;
        }
        let result = serde_json::json!({"schemaVersion": 1,
            "acceptedOverlayStreams": accepted.load(Ordering::SeqCst),
            "loopbackTcpConnections": connected.load(Ordering::SeqCst),
            "activeBridgesAfterStop": active.load(Ordering::SeqCst),
            "loopbackDestinationOnly": true});
        std::fs::write(
            control.join("peer-result.json"),
            serde_json::to_vec(&result).unwrap(),
        )
        .expect("controlled peer result");
        stage("stopped");
        std::fs::write(control.join("peer-stopped"), b"stopped").expect("controlled stop file");
        true
    });
    if !passed {
        std::process::exit(1);
    }
}

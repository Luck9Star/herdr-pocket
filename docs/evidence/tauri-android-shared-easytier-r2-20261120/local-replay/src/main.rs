use herdr_readonly_transport::{
    Audit, Cancellation, DashboardTarget, ObservationControl, ObservationPhase, RemoteConfig,
    observe_interactive_controlled_target_with_dialer, transport::SystemDialer,
};
use std::{fs, io, sync::Arc, time::Duration};
use tokio::{sync::watch, task::JoinHandle, time::timeout};

struct View {
    control: ObservationControl,
    task: JoinHandle<Result<(), &'static str>>,
    counter: watch::Receiver<u64>,
}

impl View {
    fn launch(path: &str) -> Self {
        let config = RemoteConfig::from_json(&fs::read(path).unwrap()).unwrap();
        let control = ObservationControl::new();
        let session_control = control.clone();
        let (tx, counter) = watch::channel(0);
        let task = tokio::spawn(async move {
            observe_interactive_controlled_target_with_dialer(
                config, None, Cancellation::default(), Arc::new(Audit::default()), |_| {},
                |panes| async move {
                    let pane = panes.into_iter().next().ok_or("missing_pane")?;
                    Ok(DashboardTarget { pane_id: pane.pane_id, terminal_id: pane.terminal_id })
                },
                move |_, _| {
                    tx.send_modify(|value| *value += 1);
                    async { Ok(()) }
                }, None, session_control, &SystemDialer,
            ).await
        });
        Self { control, task, counter }
    }

    async fn newer_frame(&mut self, than: u64) -> u64 {
        *timeout(Duration::from_secs(12), self.counter.wait_for(|value| *value > than))
            .await.expect("frame timeout").expect("observer ended")
    }
    async fn pause(&self) {
        assert_eq!(self.control.pause().unwrap().await.unwrap().phase, ObservationPhase::Paused);
        assert!(!self.control.graceful_peer_eof());
    }
    async fn close(self) {
        self.control.stop_gracefully();
        assert_eq!(timeout(Duration::from_secs(12), self.task).await.unwrap().unwrap(), Err("cancelled"));
        assert!(self.control.graceful_peer_eof(), "native peer EOF missing");
    }
}

fn checkpoint(name: &str) {
    println!("{name}");
    let mut line = String::new();
    io::stdin().read_line(&mut line).unwrap();
    assert_eq!(line.trim(), "next");
}

#[tokio::main]
async fn main() {
    let args = std::env::args().collect::<Vec<_>>();
    let mut a = View::launch(&args[1]);
    let mut b = View::launch(&args[2]);
    a.newer_frame(0).await;
    b.newer_frame(0).await;
    a.pause().await;
    checkpoint("both_open");
    a.close().await;
    let before = *b.counter.borrow();
    let after = b.newer_frame(before).await;
    assert!(after > before);
    checkpoint("a_closed_b_advanced");
    b.pause().await;
    b.close().await;
    checkpoint("both_closed");
}

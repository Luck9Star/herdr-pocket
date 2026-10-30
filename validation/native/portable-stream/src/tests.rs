use super::*;
use tokio::{net::{TcpListener,TcpStream}, time::timeout};
const T:Duration=Duration::from_secs(3);

async fn pair()->(TcpStream,TcpStream) {
    let listener=TcpListener::bind((std::net::Ipv4Addr::LOCALHOST,0)).await.unwrap();
    let address=listener.local_addr().unwrap();
    let (client,server)=tokio::join!(TcpStream::connect(address),listener.accept());
    let client=client.unwrap();let(server,peer)=server.unwrap();
    assert_eq!(client.local_addr().unwrap(),peer);
    assert_eq!(client.peer_addr().unwrap(),server.local_addr().unwrap());
    (client,server)
}
async fn runtime_case(body:impl std::future::Future<Output=()>){timeout(T,body).await.unwrap();}

#[tokio::test]
async fn bidirectional_bytes_half_close_and_remote_eof() {runtime_case(async {
    let registry=Registry::default();let id=registry.reserve().unwrap();
    let(remote,mut server)=pair().await;registry.complete(id,remote).unwrap();
    let input="fixture 中文\0\x1b[A".as_bytes();
    assert_eq!(registry.write(id,input,T).await.unwrap(),input.len());
    registry.shutdown_write(id,T).await.unwrap();
    let mut received=Vec::new();server.read_to_end(&mut received).await.unwrap();assert_eq!(received,input);
    server.write_all(b"response-after-half-close").await.unwrap();server.shutdown().await.unwrap();
    let mut received=Vec::new();loop {let mut buf=[0;128];let n=registry.read(id,&mut buf,T).await.unwrap();if n==0{break;}received.extend_from_slice(&buf[..n]);}
    assert_eq!(received,b"response-after-half-close");registry.close(id).await.unwrap();assert!(registry.is_empty());
}).await;}

#[tokio::test]
async fn close_unblocks_read_and_waiting_read_lock() {runtime_case(async {
    let registry=Arc::new(Registry::default());let id=registry.reserve().unwrap();
    let(remote,_server)=pair().await;registry.complete(id,remote).unwrap();
    let mut tasks=Vec::new();for _ in 0..2{let r=registry.clone();tasks.push(tokio::spawn(async move{r.read(id,&mut[0;16],T).await}));}
    tokio::task::yield_now().await;registry.close(id).await.unwrap();
    for task in tasks{assert!(matches!(task.await.unwrap(),Err(Error::Closed|Error::Invalid)));}
    assert_eq!(registry.close(id).await,Err(Error::Invalid));
}).await;}

#[tokio::test]
async fn bounded_backpressure_timeout_is_unknown_and_cancel_settles() {runtime_case(async {
    let registry=Arc::new(Registry::default());let id=registry.reserve().unwrap();
    // Remote is itself bounded and never read: no OS send buffer can hide pressure.
    let(remote,_held)=tokio::io::duplex(1);registry.complete(id,remote).unwrap();
    let data=vec![0x5a;MAX_IO];let mut accepted=0;let mut timed_out=false;
    for _ in 0..8 {match registry.write(id,&data,Duration::from_millis(20)).await{Ok(n)=>accepted+=n,Err(Error::UnknownWrite)=>{timed_out=true;break;},other=>panic!("{other:?}")}}
    assert!(timed_out);assert!(accepted<=QUEUE_BYTES+8192+1);
    let r=registry.clone();let pending=tokio::spawn(async move{r.write(id,&[1;MAX_IO],T).await});
    tokio::task::yield_now().await;registry.close(id).await.unwrap();
    assert!(matches!(pending.await.unwrap(),Err(Error::UnknownWrite|Error::Invalid|Error::Closed)));
    assert_eq!(registry.write(id,b"must-not-replay",T).await,Err(Error::Invalid));
}).await;}

#[tokio::test]
async fn cancelled_pending_connect_drops_late_stream_and_never_reuses_handle() {runtime_case(async {
    let registry=Registry::default();let stale=registry.reserve().unwrap();registry.close(stale).await.unwrap();
    let current=registry.reserve().unwrap();assert!(current>stale);
    let(late,mut peer)=pair().await;assert_eq!(registry.complete(stale,late),Err(Error::Invalid));
    assert_eq!(peer.read(&mut[0;1]).await.unwrap(),0);
    let(remote,_peer)=pair().await;registry.complete(current,remote).unwrap();
    assert_eq!(registry.close(stale).await,Err(Error::Invalid));
    assert_eq!(registry.len(),1);registry.close(current).await.unwrap();
}).await;}

#[tokio::test]
async fn pending_dial_task_is_cancelled_and_failure_released_only_by_close() {runtime_case(async {
    let registry=Registry::default();let id=registry.reserve().unwrap();
    let (sent,received)=tokio::sync::oneshot::channel::<()>();
    registry.spawn_dial(id,async move {let _owned=sent;std::future::pending::<()>().await;}).unwrap();registry.close(id).await.unwrap();
    assert!(received.await.is_err());
    let id=registry.reserve().unwrap();registry.fail(id,"synthetic connect refusal".into());
    assert!(matches!(registry.read(id,&mut[0;1],T).await,Err(Error::Failed(_))));
    assert_eq!(registry.len(),1);registry.close(id).await.unwrap();
}).await;}

#[tokio::test]
async fn capacity_limits_include_pending_and_live_ids() {
    let registry=Registry::default();let mut ids=Vec::new();for _ in 0..MAX_STREAMS{ids.push(registry.reserve().unwrap());}
    assert_eq!(registry.reserve(),Err(Error::Capacity));for id in ids{registry.close(id).await.unwrap();}
    lock(&registry.inner).next=u64::MAX;assert_eq!(registry.reserve(),Err(Error::Capacity));
}

#[tokio::test]
async fn concurrent_streams_do_not_cross_bytes_or_close_each_other() {runtime_case(async {
    let registry=Registry::default();let mut peers=Vec::new();
    for byte in 1..=4u8{let id=registry.reserve().unwrap();let(remote,mut peer)=pair().await;registry.complete(id,remote).unwrap();
        registry.write(id,&[byte;64],T).await.unwrap();let mut data=[0;64];peer.read_exact(&mut data).await.unwrap();assert_eq!(data,[byte;64]);peers.push((id,peer));}
    let(first,_)=peers.remove(0);registry.close(first).await.unwrap();
    for(id,mut peer)in peers {peer.write_all(&id.to_le_bytes()).await.unwrap();let mut got=[0;8];assert_eq!(registry.read(id,&mut got,T).await.unwrap(),8);assert_eq!(got,id.to_le_bytes());registry.close(id).await.unwrap();}
}).await;}

#[cfg(unix)]
#[test]
fn sigpipe_default_subprocess() {
    use std::os::unix::{process::ExitStatusExt,io::AsRawFd};
    const FLAG:&str="HERDR_PROBE_SIGPIPE_CHILD";
    if let Ok(mode)=std::env::var(FLAG) {
        // Only this disposable subprocess changes its signal disposition.
        unsafe{libc::signal(libc::SIGPIPE,libc::SIG_DFL);}
        if mode=="positive-control" {
            let(a,b)=std::os::unix::net::UnixStream::pair().unwrap();drop(b);
            unsafe{libc::send(a.as_raw_fd(),b"x".as_ptr().cast(),1,0);}
            panic!("default SIGPIPE positive control did not terminate");
        }
        tokio::runtime::Runtime::new().unwrap().block_on(async {
            let registry=Registry::default();let id=registry.reserve().unwrap();let(remote,peer)=pair().await;
            registry.complete(id,remote).unwrap();drop(peer);
            let mut saw_failure=false;
            for _ in 0..100 {tokio::time::sleep(Duration::from_millis(2)).await;
                if registry.write(id,b"closed-peer",T).await.is_err(){saw_failure=true;break;}}
            assert!(saw_failure,"closed peer must reach the byte stream error path");registry.close(id).await.unwrap();
        });return;
    }
    let name=format!("{}::sigpipe_default_subprocess",module_path!().split_once("::").unwrap().1);
    let run=|mode:&str|std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact",&name,"--nocapture"])
        .env(FLAG,mode).output().unwrap();
    let positive=run("positive-control");assert_eq!(positive.status.signal(),Some(libc::SIGPIPE));
    let portable=run("portable");assert!(portable.status.success(),"{}",String::from_utf8_lossy(&portable.stderr));
}

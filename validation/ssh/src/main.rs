//! CI-only loopback SSH integration probe. Never discovers credentials or known_hosts.
use std::{error::Error, fs, path::{Path, PathBuf}, sync::{Arc, atomic::{AtomicBool, Ordering}}, time::Duration};
use russh::{client, keys::{load_secret_key, PrivateKeyWithHashAlg, PublicKeyOrCertificate}, ChannelMsg, Disconnect};
use serde_json::{json, Value};
use tokio::{io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader}, net::TcpStream, time::timeout};
use herdr_probe_core::SessionGuard;
type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;
struct Pinned { expected: String, mismatched: Arc<AtomicBool> }
fn canonical(text: &str) -> String { text.split_whitespace().take(2).collect::<Vec<_>>().join(" ") }
impl client::Handler for Pinned {
    type Error = russh::Error;
    async fn check_server_key(&mut self, key: &PublicKeyOrCertificate) -> std::result::Result<bool, Self::Error> {
        let matches=canonical(&key.public_key().to_openssh().map_err(russh::Error::from)?) == self.expected;
        if !matches { self.mismatched.store(true,Ordering::SeqCst); }
        Ok(matches)
    }
}
fn path(cfg: &Value, name: &str, root: &Path) -> Result<PathBuf> {
    let p=PathBuf::from(cfg[name].as_str().ok_or("missing path")?);
    if !p.is_absolute() || !p.starts_with(root) { return Err("fixture path must remain inside isolated root".into()); }
    Ok(p)
}
fn record(root:&Path, checks:&mut Vec<Value>, value:Value)->Result<()> {
    checks.push(value);
    fs::write(root.join("ssh-results.json"),serde_json::to_vec_pretty(&json!({"schemaVersion":1,"status":"incomplete","checks":checks}))?)?;
    Ok(())
}
async fn connect(cfg: &Value, expected: String, mismatched: Arc<AtomicBool>) -> Result<client::Handle<Pinned>> {
    let port=u16::try_from(cfg["port"].as_u64().ok_or("missing port")?)?;
    if port<1024 { return Err("fixture requires a non-privileged loopback port".into()); }
    let stream=timeout(Duration::from_secs(5),TcpStream::connect(("127.0.0.1",port))).await??;
    let config=client::Config { inactivity_timeout:Some(Duration::from_secs(15)), ..Default::default() };
    Ok(timeout(Duration::from_secs(5),client::connect_stream(Arc::new(config),stream,Pinned{expected,mismatched})).await??)
}
async fn authenticate(session: &mut client::Handle<Pinned>, cfg:&Value, key:&Path) -> Result<()> {
    let private=load_secret_key(key,None)?;
    let auth=timeout(Duration::from_secs(5),session.authenticate_publickey(cfg["user"].as_str().ok_or("missing fixture user")?,PrivateKeyWithHashAlg::new(Arc::new(private),None))).await??;
    if !auth.success() { return Err("temporary public-key authentication failed".into()); } Ok(())
}
async fn rpc(session:&client::Handle<Pinned>,socket:&Path,method:&str,params:Value) -> Result<Value> {
    let channel=session.channel_open_direct_streamlocal(socket.to_str().ok_or("non-UTF8 socket")?).await?;
    let mut stream=channel.into_stream();
    stream.write_all(format!("{}\n",json!({"id":"fixture","method":method,"params":params})).as_bytes()).await?;
    let mut line=String::new();
    timeout(Duration::from_secs(8),BufReader::new(stream.take(1_048_577)).read_line(&mut line)).await??;
    if line.len()>1_048_576 || line.is_empty(){return Err("RPC empty or oversized".into());}
    let result:Value=serde_json::from_str(&line)?;
    if result["error"].is_object() || result["ok"]==false {return Err(format!("RPC rejected: {}",result["error"]).into());}
    Ok(result)
}
async fn first_frame(session:&client::Handle<Pinned>,command:&str)->Result<(Value,russh::Channel<client::Msg>)> {
    let mut channel=session.channel_open_session().await?;
    channel.exec(true,command).await?; // Deliberately no request_pty or shell fallback.
    let mut bytes=Vec::new();
    let frame=timeout(Duration::from_secs(8),async {
        while let Some(msg)=channel.wait().await {
            match msg {
                ChannelMsg::Data{data}=>{
                    bytes.extend_from_slice(&data);if bytes.len()>1_048_576{return Err::<Value,Box<dyn Error+Send+Sync>>("observe exceeded bound".into());}
                    while let Some(end)=bytes.iter().position(|b|*b==b'\n') {
                        let line:Vec<_>=bytes.drain(..=end).collect();
                        if let Ok(value)=serde_json::from_slice::<Value>(&line) {
                            if value["type"]=="terminal.frame" {return Ok(value);}
                        }
                    }
                }
                ChannelMsg::ExitStatus{exit_status}=>return Err(format!("observe exited {exit_status} before full").into()),
                _=>{}
            }
        }
        Err("observe ended before full".into())
    }).await??;
    Ok((frame,channel))
}
async fn expect_missing_session(session:&client::Handle<Pinned>,command:&str)->Result<()> {
    let mut c=session.channel_open_session().await?;c.exec(true,command).await?;
    let mut code=None;let mut output=Vec::new();
    timeout(Duration::from_secs(8),async{
        while let Some(msg)=c.wait().await {
            match msg {
                ChannelMsg::Data{data}=>{output.extend_from_slice(&data);if output.len()>65536{return Err::<(),Box<dyn Error+Send+Sync>>("missing-session output too large".into());}},
                ChannelMsg::ExitStatus{exit_status}=>code=Some(exit_status),_=>{}
            }
        } Ok(())
    }).await??;
    if code.unwrap_or(0)==0 || String::from_utf8_lossy(&output).contains("terminal.frame") {return Err("missing session unexpectedly returned a frame/success".into());} Ok(())
}
#[tokio::main]
async fn main()->Result<()> {
    if std::env::var("GITHUB_ACTIONS").as_deref()!=Ok("true") {return Err("probe runs only in isolated GitHub runner".into());}
    let root=PathBuf::from(std::env::var("HP_FIXTURE_ROOT")?);
    let cfg:Value=serde_json::from_slice(&fs::read(root.join("fixture.json"))?)?;
    let host=canonical(&fs::read_to_string(path(&cfg,"hostPublicKey",&root)?)?);
    let wrong=canonical(&fs::read_to_string(path(&cfg,"wrongPublicKey",&root)?)?);
    let key=path(&cfg,"clientPrivateKey",&root)?;
    let socket=path(&cfg,"socket",&root)?;
    let mut checks=Vec::new();
    let mismatched=Arc::new(AtomicBool::new(false));
    if connect(&cfg,wrong,mismatched.clone()).await.is_ok() || !mismatched.load(Ordering::SeqCst) {return Err("host-key mismatch was not actually observed and rejected".into());}
    record(&root,&mut checks,json!({"id":"host-key-mismatch-before-auth","status":"passed"}))?;
    let mut session=connect(&cfg,host.clone(),Arc::new(AtomicBool::new(false))).await?;authenticate(&mut session,&cfg,&key).await?;
    record(&root,&mut checks,json!({"id":"pinned-key-temporary-publickey-auth","status":"passed"}))?;
    let snapshot=rpc(&session,&socket,"session.snapshot",json!({})).await?;
    if !snapshot["result"].is_object(){return Err("snapshot missing result".into());}
    record(&root,&mut checks,json!({"id":"direct-streamlocal-real-herdr-snapshot","status":"passed"}))?;
    let pane=cfg["pane"].as_str().ok_or("missing pane")?;
    rpc(&session,&socket,"pane.send_text",json!({"pane_id":pane,"text":"A中文"})).await?;
    rpc(&session,&socket,"pane.send_keys",json!({"pane_id":pane,"keys":["up","ctrl+c","enter"]})).await?;
    let receiver=path(&cfg,"receivedBytes",&root)?;
    let expected="A中文\x1b[A\x03\r".as_bytes();
    timeout(Duration::from_secs(5),async {
        loop { if let Ok(bytes)=fs::read(&receiver) {if bytes.len()>=expected.len(){break;}} tokio::time::sleep(Duration::from_millis(25)).await; }
    }).await?;
    if fs::read(&receiver)?!=expected{return Err("actual raw PTY receiver bytes differ from submitted bytes".into());}
    record(&root,&mut checks,json!({"id":"real-input-utf8-keys-target","status":"passed","pane":pane,"expectedHex":"41e4b8ade69687 1b5b41 03 0d","receivedBytes":expected.len(),"rpcWriteAttempts":2}))?;
    let command=cfg["observeCommand"].as_str().ok_or("observe command missing")?;
    let (frame,channel)=first_frame(&session,command).await?;
    if frame["full"]!=true || frame["width"]!=80 || frame["height"]!=24 {return Err("unexpected first frame geometry/full".into());}
    channel.close().await?;
    record(&root,&mut checks,json!({"id":"explicit-session-observe-full-no-pty","status":"passed","frameKeys":frame.as_object().unwrap().keys().collect::<Vec<_>>()}))?;
    expect_missing_session(&session,cfg["missingCommand"].as_str().ok_or("missing command")?).await?;
    record(&root,&mut checks,json!({"id":"missing-session-no-default-fallback","status":"passed"}))?;
    let mut guard=SessionGuard::new(host.as_bytes().to_vec(),"pocket-probe".into())?;
    guard.authenticated_after_key(host.as_bytes())?;let old=guard.bind_session("pocket-probe")?;
    guard.cancel();session.disconnect(Disconnect::ByApplication,"probe cancellation","en").await?;
    if guard.input_allowed(old){return Err("cancelled generation permits input".into());}
    let mut session=connect(&cfg,host,Arc::new(AtomicBool::new(false))).await?;authenticate(&mut session,&cfg,&key).await?;
    let (fresh,channel)=first_frame(&session,command).await?;
    if fresh["full"]!=true {return Err("reconnect did not start at full".into());}
    channel.close().await?;session.disconnect(Disconnect::ByApplication,"probe complete","en").await?;
    tokio::time::sleep(Duration::from_millis(300)).await;
    if !root.join("capture-running").exists(){return Err("raw PTY receiver stopped before reconnect observation completed".into());}
    if fs::read(&receiver)?!=expected{return Err("receiver changed after reconnect without new input".into());}
    fs::write(root.join("stop-capture"),b"stop")?;
    record(&root,&mut checks,json!({"id":"cancel-reconnect-fresh-full-no-replayed-bytes","status":"passed","rpcWriteAttempts":2,"receivedBytesAfterReconnect":expected.len()}))?;
    let report=json!({"schemaVersion":1,"scope":"Linux loopback OpenSSH + real herdr 0.9.5; separate harness, GUI integration and overlays unverified", "checks":checks});
    fs::write(root.join("ssh-results.json"),serde_json::to_vec_pretty(&report)?)?;
    println!("{}",report);Ok(())
}

// SPDX-License-Identifier: LGPL-3.0-or-later
//! Bounded, process-local byte streams. IDs are capabilities, never OS descriptors.
//! The exact file is copied into the pinned Heeler candidate by the patch tool.
use std::{collections::HashMap, fmt, sync::{Arc, Mutex}, time::Duration};
use tokio::{io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, DuplexStream, ReadHalf, WriteHalf},
    sync::{Mutex as AsyncMutex, watch}, task::JoinHandle};

pub const MAX_STREAMS: usize = 32;
pub const MAX_IO: usize = 65_536;
pub const QUEUE_BYTES: usize = 65_536;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error { Invalid, Capacity, Closed, Timeout, UnknownWrite, Failed(String), Busy }
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result { write!(f, "{self:?}") }
}
impl std::error::Error for Error {}

struct Pipe {
    read: AsyncMutex<ReadHalf<DuplexStream>>,
    write: AsyncMutex<WriteHalf<DuplexStream>>,
}
#[derive(Clone)]
enum State { Pending, Ready(Arc<Pipe>), Failed(String), Closed }
struct Entry {
    state: watch::Sender<State>,
    stop: watch::Sender<bool>,
    tasks: Mutex<Tasks>,
}
#[derive(Default)]
struct Tasks { closed: bool, dial: Option<JoinHandle<()>>, pump: Option<JoinHandle<()>> }
struct RegistryState { next: u64, entries: HashMap<u64, Arc<Entry>> }
pub struct Registry { inner: Mutex<RegistryState> }
impl Default for Registry {
    fn default() -> Self { Self { inner: Mutex::new(RegistryState { next: 1, entries: HashMap::new() }) } }
}
fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> { m.lock().unwrap_or_else(|e|e.into_inner()) }

impl Registry {
    /// Counts both pending connects and established streams. IDs never get reused.
    pub fn reserve(&self) -> Result<u64, Error> {
        let mut inner=lock(&self.inner);
        if inner.entries.len()>=MAX_STREAMS {return Err(Error::Capacity);}
        let id=inner.next;
        inner.next=inner.next.checked_add(1).ok_or(Error::Capacity)?;
        let (state,_)=watch::channel(State::Pending);
        let (stop,_)=watch::channel(false);
        inner.entries.insert(id,Arc::new(Entry{state,stop,tasks:Mutex::new(Tasks::default())}));
        Ok(id)
    }
    fn entry(&self,id:u64)->Result<Arc<Entry>,Error> {
        lock(&self.inner).entries.get(&id).cloned().ok_or(Error::Invalid)
    }
    /// Spawn under the lifecycle lock: close always owns an already registered task.
    pub fn spawn_dial<F>(&self,id:u64,future:F)->Result<(),Error>
    where F:std::future::Future<Output=()>+Send+'static {
        let entry=self.entry(id)?;
        let mut tasks=lock(&entry.tasks);
        if tasks.closed || tasks.dial.is_some() {return Err(Error::Closed);}
        tasks.dial=Some(tokio::spawn(future));Ok(())
    }
    /// Called inside a Tokio runtime. Rejecting completion drops the owned stream.
    pub fn complete<S>(&self,id:u64,mut remote:S)->Result<(),Error>
    where S:AsyncRead+AsyncWrite+Unpin+Send+'static {
        let entry=self.entry(id)?;
        let mut tasks=lock(&entry.tasks);
        if tasks.closed || !matches!(*entry.state.borrow(),State::Pending) {return Err(Error::Closed);}
        let (client,mut pump)=tokio::io::duplex(QUEUE_BYTES);
        let (read,write)=tokio::io::split(client);
        let pipe=Arc::new(Pipe{read:AsyncMutex::new(read),write:AsyncMutex::new(write)});
        let mut stop=entry.stop.subscribe();
        tasks.pump=Some(tokio::spawn(async move {
            tokio::select! { biased;
                _=stop.changed()=>{},
                _=tokio::io::copy_bidirectional(&mut remote,&mut pump)=>{},
            }
            // Dropping both owned streams closes the connection; no input retry.
        }));
        entry.state.send_replace(State::Ready(pipe));
        Ok(())
    }
    pub fn fail(&self,id:u64,message:String) {
        if let Ok(entry)=self.entry(id) {
            let tasks=lock(&entry.tasks);
            if !tasks.closed && matches!(*entry.state.borrow(),State::Pending) {entry.state.send_replace(State::Failed(message));}
        }
    }
    async fn ready(entry:&Entry)->Result<Arc<Pipe>,Error> {
        let mut rx=entry.state.subscribe();
        loop {
            let state=rx.borrow_and_update().clone();
            match state {
                State::Ready(pipe)=>return Ok(pipe), State::Closed=>return Err(Error::Closed),
                State::Failed(message)=>return Err(Error::Failed(message)), State::Pending=>{}
            }
            rx.changed().await.map_err(|_|Error::Closed)?;
        }
    }
    pub async fn read(&self,id:u64,buf:&mut [u8],deadline:Duration)->Result<usize,Error> {
        if buf.is_empty() || buf.len()>MAX_IO {return Err(Error::Invalid);}
        let entry=self.entry(id)?;
        let mut stop=entry.stop.subscribe();
        if *stop.borrow(){return Err(Error::Closed);}
        tokio::time::timeout(deadline,async {
            tokio::select! {biased;
                _=stop.changed()=>Err(Error::Closed),
                result=async {
                    let pipe=Self::ready(&entry).await?;
                    let mut read=pipe.read.lock().await;
                    let n=read.read(buf).await.map_err(|e|Error::Failed(e.to_string()))?;
                    if *entry.stop.borrow(){Err(Error::Closed)}else{Ok(n)}
                }=>result,
            }
        }).await.map_err(|_|Error::Timeout)?
    }
    /// Positive counts acknowledge only bytes accepted into our bounded local queue.
    /// Timeout, cancellation or I/O error is UNKNOWN delivery; callers must not replay.
    pub async fn write(&self,id:u64,buf:&[u8],deadline:Duration)->Result<usize,Error> {
        if buf.is_empty() || buf.len()>MAX_IO {return Err(Error::Invalid);}
        let entry=self.entry(id)?;
        let mut stop=entry.stop.subscribe();
        if *stop.borrow(){return Err(Error::Closed);}
        tokio::time::timeout(deadline,async {
            tokio::select! {biased;
                _=stop.changed()=>Err(Error::UnknownWrite),
                result=async {
                    let pipe=Self::ready(&entry).await?;
                    let mut write=pipe.write.lock().await;
                    let n=write.write(buf).await.map_err(|_|Error::UnknownWrite)?;
                    if *entry.stop.borrow(){Err(Error::UnknownWrite)}else{Ok(n)}
                }=>result,
            }
        }).await.map_err(|_|Error::UnknownWrite)?
    }
    /// Half-close output while preserving input until the peer's EOF.
    pub async fn shutdown_write(&self,id:u64,deadline:Duration)->Result<(),Error> {
        let entry=self.entry(id)?;
        let mut stop=entry.stop.subscribe();
        if *stop.borrow(){return Err(Error::Closed);}
        tokio::time::timeout(deadline,async {
            tokio::select! {biased;
                _=stop.changed()=>Err(Error::UnknownWrite),
                result=async {
                    let pipe=Self::ready(&entry).await?;
                    pipe.write.lock().await.shutdown().await.map_err(|_|Error::UnknownWrite)
                }=>result,
            }
        }).await.map_err(|_|Error::UnknownWrite)?
    }
    /// Remove capability first. Never waits for read/write mutexes. Owns task teardown.
    pub async fn close(&self,id:u64)->Result<(),Error> {
        let entry=lock(&self.inner).entries.remove(&id).ok_or(Error::Invalid)?;
        let (dial,pump)={
            let mut tasks=lock(&entry.tasks);tasks.closed=true;
            entry.stop.send_replace(true);entry.state.send_replace(State::Closed);
            (tasks.dial.take(),tasks.pump.take())
        };
        if let Some(task)=dial {task.abort();let _=task.await;}
        if let Some(mut task)=pump {
            if tokio::time::timeout(Duration::from_secs(1),&mut task).await.is_err() {
                task.abort();let _=task.await;
            }
        }
        Ok(())
    }
    pub fn len(&self)->usize {lock(&self.inner).entries.len()}
    pub fn is_empty(&self)->bool {self.len()==0}
}

#[cfg(test)]
mod tests;

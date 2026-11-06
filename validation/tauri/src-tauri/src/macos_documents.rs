//! Native user-selected files only. No filesystem path crosses the bridge.
use std::ffi::c_void;
use tauri::{AppHandle, Runtime};
use tokio::sync::oneshot;

const LIMIT: usize = 65586;
type Reply = Result<Option<Vec<u8>>, String>;
type Callback = unsafe extern "C" fn(*const u8, usize, i32, *mut c_void);
unsafe extern "C" {
    fn pocket_document_mac_open(callback: Callback, context: *mut c_void);
    fn pocket_document_mac_save(
        bytes: *const u8,
        length: usize,
        callback: Callback,
        context: *mut c_void,
    );
}
unsafe extern "C" fn complete(bytes: *const u8, len: usize, status: i32, context: *mut c_void) {
    let sender = unsafe { Box::from_raw(context.cast::<oneshot::Sender<Reply>>()) };
    let result = match status {
        0 if len == 0 => Ok(None),
        1 if len == 0 => Ok(Some(Vec::new())), // save confirmation
        1 if len <= LIMIT && !bytes.is_null() => Ok(Some(
            unsafe { std::slice::from_raw_parts(bytes, len) }.to_vec(),
        )),
        _ => Err("document_unavailable".into()),
    };
    let _ = sender.send(result);
}
async fn invoke<R: Runtime>(app: &AppHandle<R>, bytes: Option<Vec<u8>>) -> Reply {
    let (tx, rx) = oneshot::channel();
    // Ownership is transferred only if the main-thread closure is queued.
    let slot = Box::new(tx);
    app.run_on_main_thread(move || {
        let context = Box::into_raw(slot).cast::<c_void>();
        unsafe {
            match bytes {
                None => pocket_document_mac_open(complete, context),
                Some(data) => {
                    pocket_document_mac_save(data.as_ptr(), data.len(), complete, context)
                }
            }
        }
    })
    .map_err(|_| "document_unavailable".to_string())?;
    rx.await.map_err(|_| "document_unavailable".to_string())?
}
pub async fn open_document<R: Runtime>(app: &AppHandle<R>) -> Result<Option<Vec<u8>>, String> {
    let value = invoke(app, None).await?;
    if value
        .as_ref()
        .is_some_and(|v| v.is_empty() || v.len() > LIMIT)
    {
        return Err("document_invalid".into());
    }
    Ok(value)
}
pub async fn save_document<R: Runtime>(app: &AppHandle<R>, bytes: &[u8]) -> Result<bool, String> {
    if bytes.is_empty() || bytes.len() > LIMIT {
        return Err("document_invalid".into());
    }
    Ok(invoke(app, Some(bytes.to_vec())).await?.is_some())
}

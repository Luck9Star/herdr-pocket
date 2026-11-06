#[cfg(target_os = "android")]
use base64ct::{Base64, Encoding};
use tauri::{AppHandle, Runtime};
#[cfg(target_os = "android")]
use tauri::{
    Manager,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

#[cfg(target_os = "android")]
struct Documents<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
pub fn android_plugin<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("configdocument")
        .setup(|app, api| {
            app.manage(Documents(api.register_android_plugin(
                "org.herdr.pocket",
                "ConfigDocumentPlugin",
            )?));
            Ok(())
        })
        .build()
}

#[derive(serde::Deserialize)]
#[cfg(target_os = "android")]
struct DocumentReply {
    cancelled: bool,
    archive: Option<String>,
}

#[tauri::command]
pub fn config_document_platform() -> &'static str {
    if cfg!(target_os = "android") {
        "android"
    } else if cfg!(target_os = "ios") {
        "ios"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "webview"
    }
}

#[tauri::command]
pub async fn config_document_open<R: Runtime>(
    app: AppHandle<R>,
) -> Result<Option<Vec<u8>>, String> {
    #[cfg(target_os = "android")]
    {
        let plugin = app
            .try_state::<Documents<R>>()
            .ok_or("document_unavailable")?;
        let reply: DocumentReply = plugin
            .0
            .run_mobile_plugin_async("open", ())
            .await
            .map_err(|_| "document_io_failed")?;
        if reply.cancelled {
            return Ok(None);
        }
        let data = reply
            .archive
            .filter(|s| s.len() <= 87448)
            .ok_or("document_invalid_size")?;
        return Base64::decode_vec(&data)
            .map(Some)
            .map_err(|_| "document_invalid".into());
    }
    #[cfg(target_os = "ios")]
    {
        super::ios_keys::open_document(&app).await
    }
    #[cfg(target_os = "macos")]
    {
        super::macos_documents::open_document(&app).await
    }
    #[cfg(not(any(target_os = "android", target_os = "ios", target_os = "macos")))]
    {
        let _ = app;
        Err("use_system_file_control".into())
    }
}

#[tauri::command]
pub async fn config_document_save<R: Runtime>(
    app: AppHandle<R>,
    bytes: Vec<u8>,
) -> Result<bool, String> {
    if !(51..=65586).contains(&bytes.len()) || !bytes.starts_with(b"HPKT\x01\x01") {
        return Err("document_invalid".into());
    }
    #[cfg(target_os = "android")]
    {
        let plugin = app
            .try_state::<Documents<R>>()
            .ok_or("document_unavailable")?;
        let reply: DocumentReply = plugin
            .0
            .run_mobile_plugin_async(
                "save",
                serde_json::json!({"archive":Base64::encode_string(&bytes)}),
            )
            .await
            .map_err(|_| "document_io_failed")?;
        return Ok(!reply.cancelled);
    }
    #[cfg(target_os = "ios")]
    {
        super::ios_keys::save_document(&app, &bytes).await
    }
    #[cfg(target_os = "macos")]
    {
        super::macos_documents::save_document(&app, &bytes).await
    }
    #[cfg(not(any(target_os = "android", target_os = "ios", target_os = "macos")))]
    {
        let _ = app;
        Err("use_system_file_control".into())
    }
}

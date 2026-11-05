use tauri::{AppHandle, Runtime};
#[cfg(target_os = "android")]
use tauri::{
    Manager,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

#[cfg(target_os = "android")]
struct Scanner<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
pub fn android_plugin<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("pairscan")
        .setup(|app, api| {
            let scanner = api.register_android_plugin("org.herdr.pocket", "PairScanPlugin")?;
            app.manage(Scanner(scanner));
            Ok(())
        })
        .build()
}

#[tauri::command]
pub async fn pair_scan_response<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
    #[cfg(target_os = "android")]
    {
        #[derive(serde::Deserialize)]
        struct Reply {
            text: String,
        }
        let scanner = app.try_state::<Scanner<R>>().ok_or("camera_unavailable")?;
        let reply: Reply = scanner
            .0
            .run_mobile_plugin_async("scan", serde_json::json!({}))
            .await
            .map_err(|_| "scan_cancelled_or_unavailable")?;
        if reply.text.is_empty() || reply.text.len() > 2048 {
            return Err("invalid_public_response".into());
        }
        Ok(reply.text)
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = app;
        Err("camera_unavailable".into())
    }
}

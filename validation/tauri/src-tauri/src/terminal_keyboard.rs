use tauri::{AppHandle, Runtime};

#[cfg(target_os = "android")]
use tauri::{
    plugin::{Builder, PluginHandle, TauriPlugin},
    Manager,
};

#[cfg(target_os = "android")]
struct TerminalKeyboard<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "ios")]
pub use super::ios_keys::SystemTopInset;

#[cfg(not(target_os = "ios"))]
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SystemTopInset {
    overlap_px: u32,
    system_bottom_px: i32,
    view_y: i32,
    status_px: u32,
    stable_status_px: u32,
    window_top_px: Option<i32>,
    cutout_px: Option<u32>,
    caption_px: Option<u32>,
    stable_caption_px: Option<u32>,
    ime_visible: Option<bool>,
    ime_overlap_px: Option<u32>,
    view_height_px: Option<u32>,
}

#[tauri::command]
pub async fn mobile_system_top_inset<R: Runtime>(app: AppHandle<R>) -> Result<SystemTopInset, String> {
    #[cfg(target_os = "android")]
    {
        let plugin = app.try_state::<TerminalKeyboard<R>>().ok_or("insets_unavailable")?;
        let result = plugin.0.run_mobile_plugin_async::<SystemTopInset>("topInset", serde_json::json!({})).await.map_err(|_| "insets_unavailable")?;
        Ok(result)
    }
    #[cfg(target_os = "ios")]
    { super::ios_keys::system_top_inset(&app).await }
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    { let _ = app; Err("insets_unavailable".into()) }
}

#[cfg(target_os = "android")]
pub fn android_plugin<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("pocketterminalkeyboard")
        .setup(|app, api| {
            app.manage(TerminalKeyboard(api.register_android_plugin(
                "org.herdr.pocket",
                "TerminalKeyboardPlugin",
            )?));
            Ok(())
        })
        .build()
}

#[derive(serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum KeyboardAction {
    Show,
    Hide,
}

#[tauri::command]
pub async fn mobile_terminal_keyboard<R: Runtime>(
    app: AppHandle<R>,
    ticket: String,
    action: KeyboardAction,
) -> Result<(), String> {
    if ticket.len() != 32
        || !ticket
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("keyboard_invalid_gesture".into());
    }
    #[cfg(target_os = "android")]
    {
        let plugin = app
            .try_state::<TerminalKeyboard<R>>()
            .ok_or("keyboard_unavailable")?;
        plugin
            .0
            .run_mobile_plugin_async::<serde_json::Value>(
                "request",
                serde_json::json!({ "ticket": ticket, "action": action }),
            )
            .await
            .map_err(|_| "keyboard_unavailable".to_string())?;
        Ok(())
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = (app, action);
        Err("keyboard_unavailable".into())
    }
}

use tauri::{AppHandle, Runtime};

#[cfg(target_os = "android")]
use tauri::{
    plugin::{Builder, PluginHandle, TauriPlugin},
    Manager,
};

#[cfg(target_os = "android")]
struct TerminalKeyboard<R: Runtime>(PluginHandle<R>);

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

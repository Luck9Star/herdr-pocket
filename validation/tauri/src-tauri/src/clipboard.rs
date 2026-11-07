use tauri::{AppHandle, Runtime};
#[cfg(target_os = "android")]
use tauri::{
    Manager,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

#[cfg(target_os = "android")]
struct Clipboard<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
pub fn android_plugin<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("pocketclipboard")
        .setup(|app, api| {
            app.manage(Clipboard(
                api.register_android_plugin("org.herdr.pocket", "ClipboardPlugin")?,
            ));
            Ok(())
        })
        .build()
}

#[cfg(any(target_os = "android", test))]
#[derive(serde::Deserialize)]
struct ClipboardReply {
    text: Option<String>,
    error: Option<String>,
}

#[cfg(any(target_os = "android", test))]
fn checked_reply(reply: ClipboardReply) -> Result<String, String> {
    if let Some(error) = reply.error {
        return Err(match error.as_str() {
            "clipboard_empty" => "clipboard_empty",
            "clipboard_unsupported" => "clipboard_unsupported",
            "clipboard_unfocused" => "clipboard_unfocused",
            "clipboard_too_large" => "clipboard_too_large",
            _ => "clipboard_unavailable",
        }
        .into());
    }
    let text = reply.text.ok_or("clipboard_unavailable")?;
    if text.is_empty() {
        return Err("clipboard_empty".into());
    }
    if text.len() > 4096 {
        return Err("clipboard_too_large".into());
    }
    Ok(text)
}

/// One explicit UI tap calls this once; the result remains a local draft.
#[tauri::command]
pub async fn mobile_clipboard_read_text<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
    #[cfg(target_os = "android")]
    {
        let plugin = app
            .try_state::<Clipboard<R>>()
            .ok_or("clipboard_unavailable")?;
        let reply: ClipboardReply = plugin
            .0
            .run_mobile_plugin_async("readText", ())
            .await
            .map_err(|_| "clipboard_unavailable")?;
        checked_reply(reply)
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = app;
        Err("clipboard_unavailable".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_reply_and_static_errors() {
        let reply = |text: Option<&str>, error: Option<&str>| ClipboardReply {
            text: text.map(str::to_owned),
            error: error.map(str::to_owned),
        };
        assert_eq!(checked_reply(reply(Some("文本"), None)).unwrap(), "文本");
        assert!(checked_reply(reply(Some(&"a".repeat(4096)), None)).is_ok());
        assert_eq!(
            checked_reply(reply(Some(&"界".repeat(1366)), None)).unwrap_err(),
            "clipboard_too_large"
        );
        assert_eq!(
            checked_reply(reply(Some(""), None)).unwrap_err(),
            "clipboard_empty"
        );
        assert_eq!(
            checked_reply(reply(None, None)).unwrap_err(),
            "clipboard_unavailable"
        );
        for code in [
            "clipboard_empty",
            "clipboard_unsupported",
            "clipboard_unfocused",
            "clipboard_too_large",
        ] {
            assert_eq!(checked_reply(reply(None, Some(code))).unwrap_err(), code);
        }
        assert_eq!(
            checked_reply(reply(Some("ignored"), Some("private contents"))).unwrap_err(),
            "clipboard_unavailable"
        );
    }
}

#[cfg(any(target_os = "android", test))]
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct CopyReply {
    copied: Option<bool>,
    error: Option<String>,
}

#[cfg(any(target_os = "android", test))]
fn checked_copy_reply(reply: CopyReply) -> Result<(), String> {
    if let Some(error) = reply.error {
        return Err(match error.as_str() {
            "clipboard_unfocused" => "clipboard_unfocused",
            "clipboard_too_large" => "clipboard_too_large",
            "clipboard_unsupported" => "clipboard_unsupported",
            "pairing_copy_expired" => "pairing_copy_expired",
            _ => "clipboard_unavailable",
        }.into());
    }
    if reply.copied != Some(true) { return Err("clipboard_unavailable".into()); }
    Ok(())
}

/// Native-only public pairing output. There is no frontend text argument.
#[cfg(target_os = "android")]
pub async fn write_pairing_request<R: Runtime>(app: AppHandle<R>, text: String, issued_at: u64, expires_at: u64) -> Result<(), String> {
    if text.is_empty() || text.len() > 2048 { return Err("clipboard_too_large".into()); }
    let plugin = app.try_state::<Clipboard<R>>().ok_or("clipboard_unavailable")?;
    let reply: CopyReply = plugin.0.run_mobile_plugin_async(
        "copyPairingRequest", serde_json::json!({"text":text,"issuedAt":issued_at,"expiresAt":expires_at}),
    ).await.map_err(|_| "clipboard_unavailable")?;
    checked_copy_reply(reply)
}

#[cfg(test)]
mod copy_tests {
    use super::*;
    #[test]
    fn copy_reply_is_positive_exact_and_errors_are_classified_without_request_text() {
        assert!(checked_copy_reply(CopyReply{copied:Some(true),error:None}).is_ok());
        for copied in [None,Some(false)] { assert!(checked_copy_reply(CopyReply{copied,error:None}).is_err()); }
        for error in ["clipboard_unfocused","clipboard_too_large","clipboard_unsupported","pairing_copy_expired"] {
            assert_eq!(checked_copy_reply(CopyReply{copied:None,error:Some(error.into())}).unwrap_err(),error);
        }
        assert_eq!(checked_copy_reply(CopyReply{copied:Some(true),error:Some("private contents".into())}).unwrap_err(),"clipboard_unavailable");
        assert!(serde_json::from_str::<CopyReply>(r#"{"copied":true,"text":"unexpected"}"#).is_err());
    }
}

use super::PairingState;
use base64ct::{Base64, Encoding};
use herdr_readonly_transport::{Result, pairing::KeyStore};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tauri::{
    Manager, Runtime,
    plugin::{Builder, PluginHandle, TauriPlugin},
};

#[derive(Serialize)]
struct Args<'a> {
    handle: &'a str,
    payload: &'a str,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Created {
    handle: String,
    public_key: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Public {
    public_key: String,
}
#[derive(Deserialize)]
struct Signed {
    signature: String,
}
struct AndroidStore<R: Runtime>(PluginHandle<R>);
impl<R: Runtime> KeyStore for AndroidStore<R> {
    fn create(&self) -> Result<(String, String)> {
        let r: Created = self
            .0
            .run_mobile_plugin("create", ())
            .map_err(|_| "key_unavailable")?;
        Ok((r.handle, r.public_key))
    }
    fn public(&self, handle: &str) -> Result<String> {
        let r: Public = self
            .0
            .run_mobile_plugin(
                "publicKey",
                Args {
                    handle,
                    payload: "",
                },
            )
            .map_err(|_| "key_unavailable")?;
        Ok(r.public_key)
    }
    fn sign(&self, handle: &str, data: &[u8]) -> Result<Vec<u8>> {
        if data.len() > 65536 {
            return Err("payload_too_large");
        }
        let payload = Base64::encode_string(data);
        let r: Signed = self
            .0
            .run_mobile_plugin(
                "sign",
                Args {
                    handle,
                    payload: &payload,
                },
            )
            .map_err(|_| "key_unavailable")?;
        let sig = Base64::decode_vec(&r.signature).map_err(|_| "key_unavailable")?;
        if sig.len() != 64 {
            return Err("key_unavailable");
        }
        Ok(sig)
    }
    fn delete(&self, handle: &str) -> Result<()> {
        let _: serde_json::Value = self
            .0
            .run_mobile_plugin(
                "delete",
                Args {
                    handle,
                    payload: "",
                },
            )
            .map_err(|_| "key_unavailable")?;
        Ok(())
    }
}
struct ConfigRoot<R: Runtime>(PluginHandle<R>);
#[derive(Deserialize)]
struct RootPath {
    path: String,
}
pub(crate) fn no_backup_directory<R: Runtime>(
    app: &tauri::AppHandle<R>,
) -> Result<std::path::PathBuf> {
    let state = app
        .try_state::<ConfigRoot<R>>()
        .ok_or("host_path_bridge_unavailable")?;
    let response: RootPath = state
        .0
        .run_mobile_plugin("privateConfigRoot", ())
        .map_err(|_| "host_path_bridge_unavailable")?;
    let path = std::path::PathBuf::from(response.path);
    if !path.is_absolute() {
        return Err("host_path_invalid");
    }
    Ok(path)
}
pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("devicekeys")
        .setup(|app, api| {
            let handle = api.register_android_plugin("org.herdr.pocket", "DeviceKeysPlugin")?;
            app.manage(ConfigRoot(handle.clone()));
            app.manage(PairingState::new(Arc::new(AndroidStore(handle))));
            Ok(())
        })
        .build()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct IdentityArgs<'a> {
    profile_id: &'a str,
    provider: &'a str,
    mode: &'a str,
    secret: &'a str,
    expected_handle: &'a str,
}
pub(crate) fn network_identity<R: Runtime>(
    app: &tauri::AppHandle<R>,
    operation: &str,
    profile_id: &str,
    provider: &str,
    mode: &str,
    secret: &str,
) -> std::result::Result<Option<crate::network_identity::Metadata>, String> {
    if !matches!(provider, "easytier" | "tailscale") {
        return Err("network_identity_provider_unavailable".into());
    }
    let bridge = app
        .try_state::<ConfigRoot<R>>()
        .ok_or("network_identity_unavailable")?;
    let reply: crate::network_identity::IdentityReply = bridge
        .0
        .run_mobile_plugin(
            operation,
            IdentityArgs {
                profile_id,
                provider,
                mode,
                secret,
                expected_handle: "",
            },
        )
        .map_err(|_| "network_identity_unavailable")?;
    crate::network_identity::checked_metadata(reply, provider, profile_id)
}
pub(crate) fn delete_network_identity<R: Runtime>(
    app: &tauri::AppHandle<R>,
    profile_id: &str,
    provider: &str,
    expected_handle: &str,
) -> std::result::Result<(), String> {
    let bridge = app
        .try_state::<ConfigRoot<R>>()
        .ok_or("network_identity_unavailable")?;
    let _: serde_json::Value = bridge
        .0
        .run_mobile_plugin(
            "networkIdentityDelete",
            IdentityArgs {
                profile_id,
                provider,
                mode: "",
                secret: "",
                expected_handle,
            },
        )
        .map_err(|_| "network_identity_unavailable")?;
    Ok(())
}
#[derive(Serialize)]
struct AuthArgs<'a> {
    url: &'a str,
}
pub(crate) fn open_network_auth<R: Runtime>(
    app: &tauri::AppHandle<R>,
    url: &str,
) -> std::result::Result<(), String> {
    if !crate::network_nodes::reviewed_auth_url(url) {
        return Err("network_auth_url_invalid".into());
    }
    let bridge = app
        .try_state::<ConfigRoot<R>>()
        .ok_or("network_auth_open_unavailable")?;
    let _: serde_json::Value = bridge
        .0
        .run_mobile_plugin("openNetworkAuthUrl", AuthArgs { url })
        .map_err(|_| "network_auth_open_unavailable")?;
    Ok(())
}

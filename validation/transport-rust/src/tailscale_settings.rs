//! Canonical public Tailscale settings bound into the managed node spec.
//! No auth key, identity bytes, runtime attempt or display label is accepted.
use crate::Result;
use ring::digest;

pub const DEFAULT_CONTROL_URL: &str = "https://controlplane.tailscale.com";
pub const DEFAULT_HOSTNAME: &str = "herdr-pocket";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TailscaleSettings {
    control_url: String,
    hostname: String,
    network_name: String,
}
impl TailscaleSettings {
    pub fn new(control_url: &str, hostname: &str) -> Result<Self> {
        let control_url = if control_url.is_empty() {
            DEFAULT_CONTROL_URL
        } else {
            control_url
        };
        let hostname = if hostname.is_empty() {
            DEFAULT_HOSTNAME
        } else {
            hostname
        };
        if hostname.len() > 63
            || !hostname
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-')
            || hostname.starts_with('-')
            || hostname.ends_with('-')
            || !valid_control_url(control_url)
        {
            return Err("invalid_network_binding");
        }
        let input = format!("herdr-tailscale-config-v1\0{control_url}\0{hostname}");
        let hash = digest::digest(&digest::SHA256, input.as_bytes());
        let hex: String = hash
            .as_ref()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        Ok(Self {
            control_url: control_url.into(),
            hostname: hostname.into(),
            network_name: format!("ts1:{hex}"),
        })
    }
    pub fn control_url(&self) -> &str {
        &self.control_url
    }
    pub fn hostname(&self) -> &str {
        &self.hostname
    }
    pub fn network_name(&self) -> &str {
        &self.network_name
    }
}

fn valid_control_url(value: &str) -> bool {
    if value.len() > 2048
        || !value.is_ascii()
        || value
            .bytes()
            .any(|b| b <= 32 || b == 127 || matches!(b, b'\\' | b'?' | b'#'))
    {
        return false;
    }
    let Some(rest) = value.strip_prefix("https://") else {
        return false;
    };
    let authority = rest.split('/').next().unwrap_or("");
    if authority.contains(['@', '%', '[', ']']) {
        return false;
    }
    let (host, port) = authority
        .rsplit_once(':')
        .map_or((authority, None), |(h, p)| (h, Some(p)));
    if host.is_empty()
        || host.len() > 253
        || host.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
    {
        return false;
    }
    if port.is_some_and(|p| {
        p.is_empty()
            || !p.bytes().all(|b| b.is_ascii_digit())
            || !p.parse::<u16>().is_ok_and(|n| n > 0)
    }) {
        return false;
    }
    // Preserve the user's exact public URL bytes; reject malformed escapes
    // rather than let one parser normalize a different effective setting.
    for (i, b) in value.bytes().enumerate() {
        if b == b'%'
            && !value
                .as_bytes()
                .get(i + 1..i + 3)
                .is_some_and(|pair| pair.iter().all(u8::is_ascii_hexdigit))
        {
            return false;
        }
    }
    url::Url::parse(value).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shared_vectors_and_explicit_defaults_are_identical() {
        let fixture: serde_json::Value =
            serde_json::from_str(include_str!("../../shared/tailscale-settings-v1.json")).unwrap();
        for v in fixture["vectors"].as_array().unwrap() {
            let settings = TailscaleSettings::new(
                v["controlUrl"].as_str().unwrap(),
                v["hostname"].as_str().unwrap(),
            )
            .unwrap();
            assert_eq!(settings.network_name(), v["networkName"].as_str().unwrap());
            assert_eq!(
                settings.control_url(),
                v["effectiveControlUrl"].as_str().unwrap()
            );
            assert_eq!(
                settings.hostname(),
                v["effectiveHostname"].as_str().unwrap()
            );
        }
        assert_eq!(
            TailscaleSettings::new("", "").unwrap(),
            TailscaleSettings::new(DEFAULT_CONTROL_URL, DEFAULT_HOSTNAME).unwrap()
        );
    }
    #[test]
    fn rejects_ambiguous_control_and_hostname_before_native_load() {
        let fixture: serde_json::Value =
            serde_json::from_str(include_str!("../../shared/tailscale-settings-v1.json")).unwrap();
        for v in fixture["invalid"].as_array().unwrap() {
            let control = v["controlUrl"].as_str().unwrap();
            let host = v["hostname"].as_str().unwrap();
            assert!(TailscaleSettings::new(control, host).is_err());
            let settings = crate::config_transfer::NetworkSettings::Tailscale {
                control_url: control.into(),
                hostname: host.into(),
            };
            assert!(
                crate::config_transfer::validate_network(
                    crate::config_transfer::Provider::Tailscale,
                    "shared invalid",
                    &settings
                )
                .is_err()
            );
        }
        for url in [
            "http://example.com",
            "https://u:p@example.com",
            "https://example.com?auth=secret",
            "https://example.com#x",
            "https://example.com:0",
            "https://example.com:65536",
            "https://example.com/%",
            "https://example.com/\n",
            "https://[::1]",
            "https://example..com",
            "https://-example.com",
            " https://example.com",
        ] {
            assert_eq!(
                TailscaleSettings::new(url, ""),
                Err("invalid_network_binding")
            );
        }
        for host in ["-x", "x-", "two labels", "a.b", "中", "\0"] {
            assert!(TailscaleSettings::new("", host).is_err());
        }
        assert!(TailscaleSettings::new("", &"a".repeat(64)).is_err());
        assert!(
            TailscaleSettings::new(&format!("https://example.com/{}", "a".repeat(2048)), "")
                .is_err()
        );
    }
}

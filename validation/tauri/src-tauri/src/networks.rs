//! Public network configuration only. Native provider identities are separate.
use serde::{Deserialize, Serialize};
use herdr_readonly_transport::config_transfer::validate_network;
pub use herdr_readonly_transport::config_transfer::{Provider, NetworkSettings as Settings};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
pub struct NetworkProfile {
    pub id: String,
    pub label: String,
    pub provider: Provider,
    pub enabled: bool,
    pub revision: u32,
    pub settings: Settings,
}
impl NetworkProfile {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.len()!=32 || !self.id.bytes().all(|b|b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) || !(1..=i32::MAX as u32).contains(&self.revision) {return Err("invalid_network_profile".into());}
        validate_network(self.provider,&self.label,&self.settings).map_err(|_|"invalid_network_profile".into())
    }
}
#[cfg(test)]
mod tests {
 use super::*;
 #[test] fn shared_validation_fixture() {
  let fixture:serde_json::Value=serde_json::from_str(include_str!("../../../shared/network-profiles-v1.json")).unwrap();
  for entry in fixture["validProfiles"].as_array().unwrap() {let name=entry["name"].as_str().unwrap();let profile:NetworkProfile=serde_json::from_value(entry["profile"].clone()).unwrap_or_else(|e|panic!("{name}: {e}"));assert!(profile.validate().is_ok(),"{name}");}
  for entry in fixture["invalidProfiles"].as_array().unwrap() {let name=entry["name"].as_str().unwrap();let parsed=serde_json::from_value::<NetworkProfile>(entry["profile"].clone());assert!(parsed.is_err() || parsed.unwrap().validate().is_err(),"accepted {name}");}
 }
}

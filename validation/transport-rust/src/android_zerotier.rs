//! Android-native ZeroTier source. This module requires the explicit JNI and
//! pinned native libraries; it never falls back to a system identity or socket.
use herdr_android_network_source::zerotier::{self, AndroidZeroTierReservation};
use overlay_runtime::{
    Failure, Result,
    nodes::NodeSpec,
    zerotier::{NativeDeviceConfig, NativeDeviceSession, NativeDeviceSource, validate_spec},
};
use std::{
    sync::{
        Arc, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

struct Session(Arc<AndroidZeroTierReservation>);
impl NativeDeviceSession for Session {
    fn identity_ref(&self) -> &str {
        self.0.identity_ref()
    }
    fn owner(&self) -> u64 {
        self.0.owner()
    }
    fn retire_after_network(&self, deadline: Duration) -> Result<()> {
        self.0.retire_after_network(deadline)
    }
}

/// Public immutable binding. The first valid runtime attempt freezes the full
/// spec; later attempts must construct a fresh source.
pub struct AndroidZeroTierSource {
    profile_id: String,
    profile_revision: u32,
    network: String,
    identity_ref: String,
    attempt: OnceLock<NodeSpec>,
    used: AtomicBool,
}
impl AndroidZeroTierSource {
    pub fn new(
        profile_id: String,
        profile_revision: u32,
        network: String,
        identity_ref: String,
    ) -> Result<Self> {
        if !zerotier::is_zerotier_initialized() {
            return Err(Failure::ProviderUnavailable);
        }
        if profile_id.is_empty()
            || profile_revision == 0
            || network.is_empty()
            || identity_ref.is_empty()
        {
            return Err(Failure::InvalidRoute);
        }
        Ok(Self {
            profile_id,
            profile_revision,
            network,
            identity_ref,
            attempt: OnceLock::new(),
            used: AtomicBool::new(false),
        })
    }
}
impl NativeDeviceSource for AndroidZeroTierSource {
    fn acquire(&self, spec: &NodeSpec, deadline: Duration) -> Result<NativeDeviceConfig> {
        validate_spec(spec)?;
        if spec.profile.id != self.profile_id
            || spec.profile_revision != self.profile_revision
            || spec.network != self.network
            || spec.identity_ref != self.identity_ref
        {
            return Err(Failure::StaleRevision);
        }
        if self.attempt.get_or_init(|| spec.clone()) != spec {
            return Err(Failure::StaleRevision);
        }
        if self.used.swap(true, Ordering::SeqCst) {
            return Err(Failure::Busy);
        }
        let (reservation, failure) = zerotier::acquire_device(&self.identity_ref, deadline)?;
        NativeDeviceConfig::for_spec(spec, Arc::new(Session(reservation)), failure)
    }
}

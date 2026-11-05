#[cfg(feature = "linked-easytier")]
fn main() {
    use herdr_overlay_runtime_probe::{Backend, easytier::EasyTierBackend};
    use std::sync::Arc;
    let backend: Arc<dyn Backend> = Arc::new(
        EasyTierBackend::linked("unused-abi-probe", "unused-network")
            .expect("explicit candidate ABI required"),
    );
    // Existing native close(0) is side-effect-free with respect to nodes and
    // identities. It may initialize the bridge's process-local Tokio runtime.
    backend
        .close(0)
        .expect("candidate ABI invalid-handle close must be harmless");
    println!(
        "ABI presence checked: {:?}; no node start/join/dial/identity calls",
        backend.evidence()
    );
}
#[cfg(not(feature = "linked-easytier"))]
fn main() {
    eprintln!(
        "EasyTier backend unavailable: explicitly link the candidate ABI or use the synthetic fixture feature"
    );
    std::process::exit(2);
}

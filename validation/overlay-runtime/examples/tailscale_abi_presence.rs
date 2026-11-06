fn main() {
    herdr_overlay_runtime_probe::tailscale::verify_managed_abi_presence()
        .expect("explicit Tailscale ABI and invalid-handle status required");
    println!(
        "Tailscale ABI linked/version checked; no node, login, store, socket or identity used"
    );
}

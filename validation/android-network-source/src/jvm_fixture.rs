//! Isolated desktop JVM harness exports. Not enabled in application builds.
use super::*;
use jni::sys::{JNI_FALSE, JNI_TRUE, jboolean, jint};

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidEasyTierConfig_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    if bind(&mut env, class, context) {
        JNI_TRUE
    } else {
        JNI_FALSE
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_NetworkSourceFixture_probe(
    _env: JNIEnv<'_>,
    _class: JClass<'_>,
    mode: jint,
) -> jint {
    catch_unwind(|| {
        std::thread::spawn(move || {
            let source = match AndroidSecureConfigSource::new(
                "a".repeat(32),
                7,
                "fixture".into(),
                "11111111-1111-4111-8111-111111111111".into(),
                vec!["tcp://node.invalid:11010".into()],
            ) {
                Ok(source) => source,
                Err("network_native_context_unavailable") => return 3,
                Err(_) => return 4,
            };
            let spec = NodeSpec {
                profile: overlay_runtime::ProfileKey {
                    provider: Provider::EasyTier,
                    id: "a".repeat(32),
                },
                revision: 41,
                profile_revision: if mode == 1 { 8 } else { 7 },
                network: "fixture".into(),
                identity_ref: "11111111-1111-4111-8111-111111111111".into(),
            };
            match source.load(&spec) {
                Ok(_) => 0,
                Err(Failure::StaleRevision) => 2,
                Err(_) => 1,
            }
        })
        .join()
        .unwrap_or(9)
    })
    .unwrap_or(9)
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidTailscaleConfig_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    if bind_tailscale(&mut env, class, context) {
        JNI_TRUE
    } else {
        JNI_FALSE
    }
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_TailscaleSourceFixture_probe(
    _env: JNIEnv<'_>,
    _class: JClass<'_>,
    mode: jint,
) -> jint {
    use overlay_runtime::tailscale::{NativeStateSource, NativeStateStore, StateStoreError};
    catch_unwind(|| {
        std::thread::spawn(move || {
            let spec = NodeSpec {
                profile: overlay_runtime::ProfileKey {
                    provider: Provider::Tailscale,
                    id: "a".repeat(32),
                },
                revision: 41,
                profile_revision: 7,
                network: "fixture".into(),
                identity_ref: "11111111-1111-4111-8111-111111111111".into(),
            };
            let source = match AndroidTailscaleSource::new(
                spec.profile.id.clone(),
                spec.profile_revision,
                spec.network.clone(),
                spec.identity_ref.clone(),
                "fixture".into(),
                "https://control.invalid".into(),
            ) {
                Ok(s) => s,
                Err(_) => return 3,
            };
            if mode == 17 {
                return 0;
            }
            if mode == 18 {
                if source.load(&spec).is_ok() {
                    return 9;
                }
                let mut next = spec.clone();
                next.revision += 1;
                return if matches!(source.load(&next), Err(Failure::StaleRevision)) {
                    0
                } else {
                    9
                };
            }
            if mode == 15 {
                let mut wrong = spec.clone();
                wrong.network.push('x');
                if !matches!(source.load(&wrong), Err(Failure::StaleRevision)) {
                    return 9;
                }
                wrong = spec.clone();
                wrong.revision = 0;
                if !matches!(source.load(&wrong), Err(Failure::StaleRevision)) {
                    return 9;
                }
                if source.load(&spec).is_err() {
                    return 9;
                }
                wrong = spec.clone();
                wrong.revision += 1;
                if !matches!(source.load(&wrong), Err(Failure::StaleRevision)) {
                    return 9;
                }
                return if source.load(&spec).is_ok() { 0 } else { 9 };
            }
            if mode == 16 {
                let source = Arc::new(source);
                let barrier = Arc::new(std::sync::Barrier::new(2));
                let mut joins = vec![];
                for attempt in [41, 42] {
                    let source = source.clone();
                    let barrier = barrier.clone();
                    let mut candidate = spec.clone();
                    candidate.revision = attempt;
                    joins.push(std::thread::spawn(move || {
                        barrier.wait();
                        match source.load(&candidate) {
                            Ok(_) => 0,
                            Err(Failure::StaleRevision) => 2,
                            _ => 9,
                        }
                    }));
                }
                let mut results: Vec<_> =
                    joins.into_iter().map(|j| j.join().unwrap_or(9)).collect();
                results.sort_unstable();
                return if results == [0, 2] { 0 } else { 9 };
            }
            if mode == 1 {
                if source.load(&spec).is_err() {
                    return 9;
                }
                let mut changed = spec.clone();
                changed.revision += 1;
                return if matches!(source.load(&changed), Err(Failure::StaleRevision)) {
                    2
                } else {
                    9
                };
            }
            if (2..=5).contains(&mode) {
                let mut changed = spec.clone();
                match mode {
                    1 => changed.revision += 1,
                    2 => changed.profile_revision += 1,
                    3 => changed.profile.provider = Provider::EasyTier,
                    4 => changed.network.push('x'),
                    _ => changed.identity_ref.push('x'),
                }
                return if matches!(source.load(&changed), Err(Failure::StaleRevision)) {
                    2
                } else {
                    9
                };
            }
            if mode == 13 {
                let mut changed = spec.clone();
                changed.profile.id = "b".repeat(32);
                return if matches!(source.load(&changed), Err(Failure::StaleRevision)) {
                    2
                } else {
                    9
                };
            }
            if mode == 14 {
                return if source.load(&spec).is_err() { 0 } else { 1 };
            }
            if mode == 6 {
                return if source.load(&spec).is_ok() { 0 } else { 1 };
            }
            let store = tailscale::AndroidStore {
                context: tailscale::TS_CONTEXT.get().unwrap().clone(),
                profile: spec.profile.id,
                handle: spec.identity_ref,
            };
            match mode {
                7 => {
                    if store.read(&[0xff, 0, 0x80]) == Err(StateStoreError::Missing) {
                        0
                    } else {
                        1
                    }
                }
                8 => {
                    if store.write(&[0xff, 0, 0x80], Some(&[])).is_ok()
                        && store.read(&[0xff, 0, 0x80]) == Ok(vec![])
                    {
                        0
                    } else {
                        1
                    }
                }
                9 => {
                    if store.write(&[], Some(&[1, 2, 3])).is_ok()
                        && store.read(&[]) == Ok(vec![1, 2, 3])
                        && store.write(&[], None).is_ok()
                        && store.read(&[]) == Err(StateStoreError::Missing)
                    {
                        0
                    } else {
                        1
                    }
                }
                10 => {
                    if store.read(&[1]) == Err(StateStoreError::Unavailable) {
                        0
                    } else {
                        1
                    }
                }
                11 => {
                    if store.read(&vec![1; 1025]) == Err(StateStoreError::Unavailable)
                        && store.write(&[1], Some(&vec![2; 262145]))
                            == Err(StateStoreError::Unavailable)
                    {
                        0
                    } else {
                        1
                    }
                }
                12 => {
                    if store.write(&vec![0xff; 1024], Some(&[7; 10])).is_ok()
                        && store.read(&vec![0xff; 1024]) == Ok(vec![7; 10])
                    {
                        0
                    } else {
                        1
                    }
                }
                _ => 9,
            }
        })
        .join()
        .unwrap_or(9)
    })
    .unwrap_or(9)
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_TailscaleSourceFixture_bindClass(
    mut env: JNIEnv<'_>,
    _class: JClass<'_>,
    candidate: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    if bind_tailscale(&mut env, candidate, context) {
        JNI_TRUE
    } else {
        JNI_FALSE
    }
}

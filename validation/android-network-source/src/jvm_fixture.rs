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

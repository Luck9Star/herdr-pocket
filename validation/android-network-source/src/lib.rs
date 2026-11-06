//! JNI-only vault configuration source. No secret-bearing IPC command or
//! JNI_OnLoad; the host binds its application Context and originating class.
pub use jni;
use jni::{
    JNIEnv, JavaVM,
    objects::{GlobalRef, JByteArray, JClass, JObject, JValue},
};
use overlay_runtime::{
    Failure, Provider,
    nodes::{NodeSpec, SecretConfig, SecureConfigSource},
};
use std::{
    panic::{AssertUnwindSafe, catch_unwind},
    sync::{Arc, OnceLock},
};
use zeroize::Zeroizing;

struct Context {
    vm: JavaVM,
    application: GlobalRef,
    config_class: GlobalRef,
}
static CONTEXT: OnceLock<Arc<Context>> = OnceLock::new();

/// Native host initialization only; this does not imply vault access or a route.
pub fn is_initialized() -> bool {
    CONTEXT.get().is_some()
}

/// Called only from AndroidEasyTierConfig.bindNative on an already attached
/// Java thread. Retains application context, never the Activity. A different
/// VM, app context, or class loader cannot replace an established binding.
/// JNI exceptions are cleared without describing/logging their contents.
pub fn bind(env: &mut JNIEnv<'_>, class: JClass<'_>, context: JObject<'_>) -> bool {
    let result = catch_unwind(AssertUnwindSafe(|| bind_inner(env, class, context)));
    let pending = env.exception_check().unwrap_or(true);
    if pending {
        let _ = env.exception_clear();
    }
    !pending && matches!(result, Ok(Ok(())))
}

fn bind_inner(
    env: &mut JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jni::errors::Result<()> {
    if context.is_null() || class.is_null() {
        return Err(jni::errors::Error::NullPtr("context"));
    }
    let application = env
        .call_method(
            &context,
            "getApplicationContext",
            "()Landroid/content/Context;",
            &[],
        )?
        .l()?;
    if application.is_null() {
        return Err(jni::errors::Error::NullPtr("application"));
    }
    let application = env.auto_local(application);
    // Resolve the exact signature now, on the app's class-loader thread.
    env.get_static_method_id(&class, "load", "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;)[B")?;
    let candidate = Arc::new(Context {
        vm: env.get_java_vm()?,
        application: env.new_global_ref(&application)?,
        config_class: env.new_global_ref(&class)?,
    });
    if let Err(candidate) = CONTEXT.set(candidate) {
        let previous = CONTEXT
            .get()
            .ok_or(jni::errors::Error::NullPtr("binding"))?;
        if previous.vm.get_java_vm_pointer() != candidate.vm.get_java_vm_pointer()
            || !env.is_same_object(
                previous.application.as_obj(),
                candidate.application.as_obj(),
            )?
            || !env.is_same_object(
                previous.config_class.as_obj(),
                candidate.config_class.as_obj(),
            )?
        {
            return Err(jni::errors::Error::NullPtr("changed binding"));
        }
    }
    Ok(())
}

/// Immutable public binding, including peers. Construct separately per start.
/// Debug/Clone are intentionally omitted to discourage accidental logging.
pub struct AndroidSecureConfigSource {
    context: Arc<Context>,
    profile_id: String,
    profile_revision: u32,
    network_name: String,
    identity_ref: String,
    peers: Vec<String>,
}
impl AndroidSecureConfigSource {
    pub fn new(
        profile_id: String,
        profile_revision: u32,
        network_name: String,
        identity_ref: String,
        peers: Vec<String>,
    ) -> Result<Self, &'static str> {
        validate_binding(
            &profile_id,
            profile_revision,
            &network_name,
            &identity_ref,
            &peers,
        )?;
        let context = CONTEXT
            .get()
            .cloned()
            .ok_or("network_native_context_unavailable")?;
        Ok(Self {
            context,
            profile_id,
            profile_revision,
            network_name,
            identity_ref,
            peers,
        })
    }
    fn matches(&self, spec: &NodeSpec) -> bool {
        spec.profile.provider == Provider::EasyTier
            && spec.profile.id == self.profile_id
            && spec.profile_revision == self.profile_revision
            && spec.network == self.network_name
            && spec.identity_ref == self.identity_ref
    }
    fn load_native(&self) -> Result<SecretConfig, Failure> {
        let mut env = self
            .context
            .vm
            .attach_current_thread()
            .map_err(|_| Failure::IdentityUnavailable)?;
        let result = env.with_local_frame(48, |env| self.read_configuration(env));
        let pending = env.exception_check().unwrap_or(true);
        if pending {
            let _ = env.exception_clear();
        }
        if pending {
            return Err(Failure::IdentityUnavailable);
        }
        result.map_err(|_| Failure::IdentityUnavailable)
    }
    fn read_configuration(&self, env: &mut JNIEnv<'_>) -> jni::errors::Result<SecretConfig> {
        let profile = env.new_string(&self.profile_id)?;
        let handle = env.new_string(&self.identity_ref)?;
        let network = env.new_string(&self.network_name)?;
        let peers =
            env.new_object_array(self.peers.len() as i32, "java/lang/String", JObject::null())?;
        for (index, peer) in self.peers.iter().enumerate() {
            let value = env.auto_local(env.new_string(peer)?);
            env.set_object_array_element(&peers, index as i32, &value)?;
        }
        // A cached GlobalRef avoids FindClass(app class) from a Rust worker.
        let class: &JClass<'_> = self.context.config_class.as_obj().into();
        let object = env.call_static_method(class, "load",
            "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;)[B",
            &[JValue::Object(self.context.application.as_obj()), JValue::Object(&profile),
                JValue::Object(&handle), JValue::Object(&network), JValue::Object(&peers)])?.l()?;
        let array = JByteArray::from(object);
        if array.is_null() {
            return Err(jni::errors::Error::NullPtr("configuration"));
        }
        let count = env.get_array_length(&array)? as usize;
        // Clear the Java array on every bounded payload result, including errors.
        // Java independently caps output; oversize arrays are cleared in chunks.
        let result = if count == 0 || count > overlay_runtime::MAX_IO {
            Err(jni::errors::Error::NullPtr("configuration bound"))
        } else {
            env.convert_byte_array(&array).and_then(|bytes| {
                let mut bytes = Zeroizing::new(bytes);
                if bytes.contains(&0) || std::str::from_utf8(&bytes).is_err() {
                    return Err(jni::errors::Error::NullPtr("configuration encoding"));
                }
                // All SecretConfig rejection conditions were checked before
                // transferring ownership to its volatile-erasing Drop.
                SecretConfig::from_bytes(std::mem::take(&mut *bytes))
                    .map_err(|_| jni::errors::Error::NullPtr("configuration bound"))
            })
        };
        // No Java exception should be pending for the byte copy, but clear any
        // failure first so cleanup remains legal JNI. Never ExceptionDescribe.
        if env.exception_check()? {
            env.exception_clear()?;
        }
        let zero = [0_i8; 1024];
        for offset in (0..count).step_by(zero.len()) {
            env.set_byte_array_region(
                &array,
                offset as i32,
                &zero[..(count - offset).min(zero.len())],
            )?;
        }
        result
    }
}
impl SecureConfigSource for AndroidSecureConfigSource {
    fn load(&self, spec: &NodeSpec) -> Result<SecretConfig, Failure> {
        if !self.matches(spec) {
            return Err(Failure::StaleRevision);
        }
        catch_unwind(AssertUnwindSafe(|| self.load_native()))
            .unwrap_or(Err(Failure::IdentityUnavailable))
    }
}

fn validate_binding(
    profile: &str,
    revision: u32,
    network: &str,
    handle: &str,
    peers: &[String],
) -> Result<(), &'static str> {
    let valid_id = profile.len() == 32
        && profile
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b));
    let b = handle.as_bytes();
    let valid_handle = b.len() == 36
        && b.iter().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => *c == b'-',
            14 => *c == b'4',
            19 => matches!(*c, b'8' | b'9' | b'a' | b'b'),
            _ => c.is_ascii_digit() || (b'a'..=b'f').contains(c),
        });
    if !valid_id
        || !(1..=i32::MAX as u32).contains(&revision)
        || !valid_handle
        || network.trim().is_empty()
        || network.len() > 64
        || network.chars().any(char::is_control)
        || peers.is_empty()
        || peers.len() > 16
        || peers.iter().any(|p| {
            p.is_empty()
                || p.len() > 2048
                || !p.is_ascii()
                || p.bytes()
                    .any(|b| b.is_ascii_whitespace() || b.is_ascii_control())
        })
    {
        return Err("invalid_network_binding");
    }
    Ok(()) // The native Java builder performs the full public URL validation.
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounds_before_jni_context_access() {
        let p = "a".repeat(32);
        let h = "11111111-1111-4111-8111-111111111111";
        let peers = vec!["tcp://node.invalid:11010".into()];
        assert!(validate_binding(&p, 1, "fixture", h, &peers).is_ok());
        for revision in [0, u32::MAX] {
            assert!(validate_binding(&p, revision, "fixture", h, &peers).is_err());
        }
        assert!(validate_binding("../profile", 1, "fixture", h, &peers).is_err());
        assert!(validate_binding(&p, 1, "a\nb", h, &peers).is_err());
        assert!(validate_binding(&p, 1, "fixture", "invalid", &peers).is_err());
        assert!(validate_binding(&p, 1, "fixture", h, &vec!["tcp://x:1".into(); 17]).is_err());
        assert!(validate_binding(&p, 1, "fixture", h, &["tcp://x:1\n".into()]).is_err());
    }
    #[test]
    fn absent_context_does_not_fall_back() {
        let result = AndroidSecureConfigSource::new(
            "a".repeat(32),
            1,
            "fixture".into(),
            "11111111-1111-4111-8111-111111111111".into(),
            vec!["tcp://node.invalid:11010".into()],
        );
        assert!(matches!(result, Err("network_native_context_unavailable")));
    }
}

#[cfg(feature = "jvm-fixture")]
mod jvm_fixture;

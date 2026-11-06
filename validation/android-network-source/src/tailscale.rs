//! Android-owned Tailscale custody; state crosses JNI only on native workers.
use super::*;
use overlay_runtime::tailscale::{
    MAX_STATE_KEY, MAX_STATE_VALUE, NativeNodeConfig, NativeStateSource, NativeStateStore,
    NativeVettedDirectory, StateStoreError, StateStoreResult,
};
use std::path::PathBuf;
use zeroize::Zeroize;

pub(super) static TS_CONTEXT: OnceLock<Arc<Context>> = OnceLock::new();
const DIR: &str =
    "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;";
const READ: &str = "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;[B)[B";
const WRITE: &str = "(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;[B[B)V";
const MISSING: &str = "(Ljava/lang/Throwable;)Z";

pub fn is_tailscale_initialized() -> bool {
    TS_CONTEXT.get().is_some()
}
/// Called on the app class-loader thread, never from JNI_OnLoad.
pub fn bind_tailscale(env: &mut JNIEnv<'_>, class: JClass<'_>, context: JObject<'_>) -> bool {
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
    if class.is_null() || context.is_null() {
        return Err(jni::errors::Error::NullPtr("binding"));
    }
    let app = env
        .call_method(
            context,
            "getApplicationContext",
            "()Landroid/content/Context;",
            &[],
        )?
        .l()?;
    if app.is_null() {
        return Err(jni::errors::Error::NullPtr("application"));
    }
    let app = env.auto_local(app);
    for (name, sig) in [
        ("directory", DIR),
        ("read", READ),
        ("write", WRITE),
        ("isMissing", MISSING),
    ] {
        env.get_static_method_id(&class, name, sig)?;
    }
    let candidate = Arc::new(Context {
        vm: env.get_java_vm()?,
        application: env.new_global_ref(&app)?,
        config_class: env.new_global_ref(&class)?,
    });
    if let Err(candidate) = TS_CONTEXT.set(candidate) {
        let previous = TS_CONTEXT
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

/// Public binding is fixed at construction; the first valid load freezes its attempt.
pub struct AndroidTailscaleSource {
    context: Arc<Context>,
    profile_id: String,
    profile_revision: u32,
    network: String,
    identity_ref: String,
    bound_spec: OnceLock<NodeSpec>,
    hostname: String,
    control_url: String,
}
impl AndroidTailscaleSource {
    pub fn new(
        profile_id: String,
        profile_revision: u32,
        network: String,
        identity_ref: String,
        hostname: String,
        control_url: String,
    ) -> Result<Self, &'static str> {
        let p = &profile_id;
        let h = identity_ref.as_bytes();
        if profile_revision == 0
            || p.len() != 32
            || !p
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || h.len() != 36
            || !h.iter().enumerate().all(|(i, c)| match i {
                8 | 13 | 18 | 23 => *c == b'-',
                14 => *c == b'4',
                19 => matches!(*c, b'8' | b'9' | b'a' | b'b'),
                _ => c.is_ascii_digit() || (b'a'..=b'f').contains(c),
            })
            || network.is_empty()
            || network.len() > 256
            || network.chars().any(char::is_control)
        {
            return Err("invalid_network_binding");
        }
        let context = TS_CONTEXT
            .get()
            .cloned()
            .ok_or("network_native_context_unavailable")?;
        Ok(Self {
            context,
            profile_id,
            profile_revision,
            network,
            identity_ref,
            bound_spec: OnceLock::new(),
            hostname,
            control_url,
        })
    }
    fn directory(&self) -> Result<NativeVettedDirectory, Failure> {
        let mut env = self
            .context
            .vm
            .attach_current_thread()
            .map_err(|_| Failure::IdentityUnavailable)?;
        let result = env.with_local_frame(16, |env| -> jni::errors::Result<String> {
            let p = env.new_string(&self.profile_id)?;
            let h = env.new_string(&self.identity_ref)?;
            let class: &JClass<'_> = self.context.config_class.as_obj().into();
            let result = env
                .call_static_method(
                    class,
                    "directory",
                    DIR,
                    &[
                        JValue::Object(self.context.application.as_obj()),
                        JValue::Object(&p),
                        JValue::Object(&h),
                    ],
                )?
                .l()?;
            if result.is_null() {
                return Err(jni::errors::Error::NullPtr("directory"));
            }
            Ok(env.get_string(&jni::objects::JString::from(result))?.into())
        });
        if env.exception_check().unwrap_or(true) {
            let _ = env.exception_clear();
            return Err(Failure::IdentityUnavailable);
        }
        let path = result.map_err(|_| Failure::IdentityUnavailable)?;
        NativeVettedDirectory::from_native_vetted(PathBuf::from(path))
    }
}
impl NativeStateSource for AndroidTailscaleSource {
    fn load(&self, spec: &NodeSpec) -> Result<NativeNodeConfig, Failure> {
        if spec.profile.provider != Provider::Tailscale
            || spec.profile.id != self.profile_id
            || spec.profile_revision != self.profile_revision
            || spec.network != self.network
            || spec.identity_ref != self.identity_ref
            || spec.revision == 0
        {
            return Err(Failure::StaleRevision);
        }
        let bound = self.bound_spec.get_or_init(|| spec.clone());
        if bound != spec {
            return Err(Failure::StaleRevision);
        }
        catch_unwind(AssertUnwindSafe(|| {
            let directory = self.directory()?;
            let store = Arc::new(AndroidStore {
                context: self.context.clone(),
                profile: self.profile_id.clone(),
                handle: self.identity_ref.clone(),
            });
            NativeNodeConfig::for_spec(
                spec,
                directory,
                self.hostname.clone(),
                self.control_url.clone(),
                store,
            )
        }))
        .unwrap_or(Err(Failure::IdentityUnavailable))
    }
}
pub(super) struct AndroidStore {
    pub(super) context: Arc<Context>,
    pub(super) profile: String,
    pub(super) handle: String,
}
fn wipe(env: &mut JNIEnv<'_>, array: &JByteArray<'_>) -> jni::errors::Result<()> {
    let len = env.get_array_length(array)? as usize;
    let zeros = [0_i8; 1024];
    for offset in (0..len).step_by(zeros.len()) {
        env.set_byte_array_region(
            array,
            offset as i32,
            &zeros[..(len - offset).min(zeros.len())],
        )?;
    }
    Ok(())
}
impl AndroidStore {
    fn call(&self, key: &[u8], value: Option<Option<&[u8]>>) -> StateStoreResult<Vec<u8>> {
        if key.len() > MAX_STATE_KEY || value.flatten().is_some_and(|v| v.len() > MAX_STATE_VALUE) {
            return Err(StateStoreError::Unavailable);
        }
        let mut env = self
            .context
            .vm
            .attach_current_thread()
            .map_err(|_| StateStoreError::Unavailable)?;
        let mut result = env.with_local_frame(
            24,
            |env| -> jni::errors::Result<StateStoreResult<Vec<u8>>> {
                let p = env.new_string(&self.profile)?;
                let h = env.new_string(&self.handle)?;
                let k = env.byte_array_from_slice(key)?;
                let v = match value.flatten() {
                    Some(bytes) => match env.byte_array_from_slice(bytes) {
                        Ok(array) => Some(array),
                        Err(error) => {
                            if env.exception_check().unwrap_or(false) {
                                let _ = env.exception_clear();
                            }
                            let _ = wipe(env, &k);
                            return Err(error);
                        }
                    },
                    None => None,
                };
                let null = JObject::null();
                let vobj: &JObject<'_> = v.as_ref().map(|x| x.as_ref()).unwrap_or(&null);
                let class: &JClass<'_> = self.context.config_class.as_obj().into();
                let base = [
                    JValue::Object(self.context.application.as_obj()),
                    JValue::Object(&p),
                    JValue::Object(&h),
                    JValue::Object(&k),
                ];
                let called = match value {
                    None => env.call_static_method(class, "read", READ, &base),
                    Some(_) => env.call_static_method(
                        class,
                        "write",
                        WRITE,
                        &[base[0], base[1], base[2], base[3], JValue::Object(vobj)],
                    ),
                };
                let mut missing = false;
                let mut output = Err(StateStoreError::Unavailable);
                let processed = (|| -> jni::errors::Result<()> {
                    match called {
                        Ok(result) if value.is_none() => {
                            let object = result.l()?;
                            if !object.is_null() {
                                let arr = JByteArray::from(object);
                                let len = env.get_array_length(&arr)? as usize;
                                if len <= MAX_STATE_VALUE {
                                    output = env
                                        .convert_byte_array(&arr)
                                        .map_err(|_| StateStoreError::Unavailable);
                                }
                                if env.exception_check()? {
                                    env.exception_clear()?;
                                    output = Err(StateStoreError::Unavailable);
                                }
                                if wipe(env, &arr).is_err() {
                                    if let Ok(ref mut bytes) = output {
                                        bytes.zeroize();
                                    }
                                    output = Err(StateStoreError::Unavailable);
                                }
                            }
                        }
                        Ok(_) => output = Ok(Vec::new()),
                        Err(_) => {
                            if env.exception_check()? {
                                let throwable = env.exception_occurred()?;
                                env.exception_clear()?;
                                if value.is_none() {
                                    missing = env
                                        .call_static_method(
                                            class,
                                            "isMissing",
                                            MISSING,
                                            &[JValue::Object(&throwable)],
                                        )
                                        .and_then(|r| r.z())
                                        .unwrap_or(false);
                                    if env.exception_check()? {
                                        env.exception_clear()?;
                                        missing = false;
                                    }
                                }
                            }
                        }
                    }
                    Ok(())
                })();
                if processed.is_err() || env.exception_check().unwrap_or(true) {
                    let _ = env.exception_clear();
                    if let Ok(ref mut bytes) = output {
                        bytes.zeroize();
                    }
                    output = Err(StateStoreError::Unavailable);
                    missing = false;
                }
                if wipe(env, &k).is_err() {
                    if let Ok(ref mut bytes) = output {
                        bytes.zeroize();
                    }
                    output = Err(StateStoreError::Unavailable);
                    missing = false;
                }
                if let Some(ref arr) = v
                    && wipe(env, arr).is_err()
                {
                    if let Ok(ref mut bytes) = output {
                        bytes.zeroize();
                    }
                    output = Err(StateStoreError::Unavailable);
                    missing = false;
                }
                Ok(if missing {
                    Err(StateStoreError::Missing)
                } else {
                    output
                })
            },
        );
        if env.exception_check().unwrap_or(true) {
            let _ = env.exception_clear();
            if let Ok(Ok(ref mut bytes)) = result {
                bytes.zeroize();
            }
            return Err(StateStoreError::Unavailable);
        }
        result.unwrap_or(Err(StateStoreError::Unavailable))
    }
}
impl NativeStateStore for AndroidStore {
    fn read(&self, key: &[u8]) -> StateStoreResult<Vec<u8>> {
        catch_unwind(AssertUnwindSafe(|| self.call(key, None)))
            .unwrap_or(Err(StateStoreError::Unavailable))
    }
    fn write(&self, key: &[u8], value: Option<&[u8]>) -> StateStoreResult<()> {
        catch_unwind(AssertUnwindSafe(|| self.call(key, Some(value))))
            .unwrap_or(Err(StateStoreError::Unavailable))
            .map(|_| ())
    }
}

//! JNI methods are invoked only by Kotlin's bounded non-UI lanes. Native ABI
//! work remains in OverlayRuntime workers; this file never returns config bytes.
use super::*;
use jni::{
    JNIEnv,
    objects::{JByteArray, JClass, JObject, JString},
    sys::{jboolean, jlong, jobjectArray, jstring},
};
use std::{
    panic::{AssertUnwindSafe, catch_unwind},
    ptr,
    sync::OnceLock,
};

static BRIDGE: OnceLock<Result<Arc<Bridge>>> = OnceLock::new();
fn bridge() -> Result<&'static Arc<Bridge>> {
    BRIDGE
        .get_or_init(|| Bridge::new(Arc::new(AndroidSource)))
        .as_ref()
        .map_err(|code| *code)
}
fn string(env: &mut JNIEnv<'_>, value: JString<'_>, limit: usize) -> Result<String> {
    if value.is_null() {
        return Err("invalid_network_request");
    }
    let count = env
        .call_method(&value, "length", "()I", &[])
        .and_then(|v| v.i())
        .map_err(|_| "invalid_network_request")?;
    if count < 0 || count as usize > limit {
        return Err("invalid_network_request");
    }
    let output: String = env
        .get_string(&value)
        .map_err(|_| "invalid_network_request")?
        .into();
    if output.len() > limit {
        return Err("invalid_network_request");
    }
    Ok(output)
}
fn clear(env: &mut JNIEnv<'_>) -> bool {
    if env.exception_check().unwrap_or(true) {
        let _ = env.exception_clear();
        true
    } else {
        false
    }
}
fn envelope(value: Result<Value>) -> String {
    match value {
        Ok(value) => json!({"ok":true,"value":value}).to_string(),
        Err(code) => json!({"ok":false,"error":code}).to_string(),
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidEasyTierConfig_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    herdr_android_network_source::bind(&mut env, class, context) as jboolean
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidTailscaleConfig_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    herdr_android_network_source::bind_tailscale(&mut env, class, context) as jboolean
}

#[cfg(feature = "network-zerotier")]
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    herdr_android_network_source::bind_zerotier(&mut env, class, context) as jboolean
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_herdr_pocket_NetworkRuntimeChannel_nativeCreateScope(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
) -> jlong {
    let result = catch_unwind(AssertUnwindSafe(|| bridge()?.new_scope()));
    if clear(&mut env) {
        return 0;
    }
    match result {
        Ok(Ok(scope)) => scope as jlong,
        _ => 0,
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_herdr_pocket_NetworkRuntimeChannel_nativeReserveOpen(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    scope: jlong,
    raw: JString<'_>,
) -> jstring {
    let result = catch_unwind(AssertUnwindSafe(|| {
        if scope <= 0 {
            return Err("network_scope_unavailable");
        }
        let id = string(&mut env, raw, 20)?;
        bridge()?.reserve_open(scope as u64, &id)
    }))
    .unwrap_or(Err("network_failed"));
    if clear(&mut env) {
        return ptr::null_mut();
    }
    match env.new_string(envelope(result)) {
        Ok(value) => value.into_raw(),
        Err(_) => {
            clear(&mut env);
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_herdr_pocket_NetworkRuntimeChannel_nativeCloseScope(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    scope: jlong,
) -> jstring {
    let result = catch_unwind(AssertUnwindSafe(|| {
        if scope <= 0 {
            return Err("network_scope_unavailable");
        }
        bridge()?.close_scope(scope as u64)
    }))
    .unwrap_or(Err("network_failed"));
    if clear(&mut env) {
        return ptr::null_mut();
    }
    match env.new_string(envelope(result)) {
        Ok(value) => value.into_raw(),
        Err(_) => {
            clear(&mut env);
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_herdr_pocket_NetworkRuntimeChannel_nativeCall(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    scope: jlong,
    method: JString<'_>,
    args: JString<'_>,
    payload: JByteArray<'_>,
) -> jobjectArray {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<Reply> {
        if scope <= 0 {
            return Err("network_scope_unavailable");
        }
        let method = string(&mut env, method, 32)?;
        let args = string(&mut env, args, 40_000)?;
        let mut payload = Zeroizing::new(if payload.is_null() {
            Vec::new()
        } else {
            if env
                .get_array_length(&payload)
                .map_err(|_| "invalid_network_request")? as usize
                > MAX_BYTES
            {
                return Err("invalid_network_request");
            }
            env.convert_byte_array(&payload)
                .map_err(|_| "invalid_network_request")?
        });
        if method != "streamWrite" && !payload.is_empty() {
            return Err("invalid_network_request");
        }
        let bridge = bridge()?;
        bridge.executor.block_on(bridge.call(
            scope as u64,
            &method,
            &args,
            std::mem::take(&mut *payload),
        ))
    }))
    .unwrap_or(Err("network_failed"));
    if clear(&mut env) {
        return ptr::null_mut();
    }
    let (metadata, bytes) = match result {
        Ok(reply) => (envelope(Ok(reply.value)), reply.bytes),
        Err(code) => (envelope(Err(code)), None),
    };
    let output = (|| -> jni::errors::Result<jobjectArray> {
        let array = env.new_object_array(2, "java/lang/Object", JObject::null())?;
        let metadata = env.new_string(metadata)?;
        env.set_object_array_element(&array, 0, &metadata)?;
        if let Some(bytes) = bytes {
            let bytes = Zeroizing::new(bytes);
            let data = env.byte_array_from_slice(&bytes)?;
            env.set_object_array_element(&array, 1, &data)?;
        }
        Ok(array.into_raw())
    })();
    match output {
        Ok(array) if !clear(&mut env) => array,
        _ => {
            clear(&mut env);
            ptr::null_mut()
        }
    }
}

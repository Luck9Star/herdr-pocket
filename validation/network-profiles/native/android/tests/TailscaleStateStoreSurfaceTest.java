package org.herdr.network;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

/** Compile/reflection boundary only; it never constructs AndroidKeyStore. */
public final class TailscaleStateStoreSurfaceTest {
    public static void main(String[] args) throws Exception {
        Class<?> type = AndroidTailscaleStateStore.class;
        Set<String> publicMethods = Arrays.stream(type.getDeclaredMethods()).filter(m -> Modifier.isPublic(m.getModifiers()))
            .map(Method::getName).collect(Collectors.toSet());
        if (!publicMethods.equals(Set.of("create","status","delete"))) throw new AssertionError("public API leaked state");
        Method read = type.getDeclaredMethod("readState",String.class,String.class,String.class);
        Method write = type.getDeclaredMethod("writeState",String.class,String.class,String.class,byte[].class);
        Method readBytes = type.getDeclaredMethod("readStateBytes",String.class,String.class,byte[].class);
        Method writeBytes = type.getDeclaredMethod("writeStateBytes",String.class,String.class,byte[].class,byte[].class);
        Method dir = type.getDeclaredMethod("runtimeDirectory",String.class,String.class);
        if (Modifier.isPublic(read.getModifiers()) || Modifier.isPublic(write.getModifiers()) || Modifier.isPublic(dir.getModifiers()) || Modifier.isPublic(readBytes.getModifiers()) || Modifier.isPublic(writeBytes.getModifiers()) ||
            readBytes.getReturnType() != byte[].class || writeBytes.getReturnType() != void.class || read.getReturnType() != byte[].class || write.getReturnType() != void.class || dir.getReturnType() != String.class)
            throw new AssertionError("JNI-only signature");
        Set<String> fields = Arrays.stream(AndroidTailscaleStateStore.Result.class.getFields()).map(f -> f.getName()).collect(Collectors.toSet());
        if (!fields.equals(Set.of("profileId","provider","handle","instanceId"))) throw new AssertionError("reference-only result");
        System.out.println("PASS: lifecycle surface and JNI-only signatures (Android classes stubbed; no GUI channel runtime)");
    }
}

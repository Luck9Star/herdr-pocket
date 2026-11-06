package org.herdr.network;

import android.content.Context;
import android.os.Process;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;

/** JNI-only bridge. Never register these state methods on a GUI channel. */
public final class AndroidTailscaleConfig {
    private AndroidTailscaleConfig() { }
    public static native boolean bindNative(Context context);

    static String directory(Context app, String profile, String handle) throws Exception {
        String value = new AndroidTailscaleStateStore(app).runtimeDirectory(profile, handle);
        Path base = app.getNoBackupFilesDir().toPath().toRealPath(LinkOption.NOFOLLOW_LINKS);
        Path root = base.resolve("herdr-tailscale-state-v1");
        Path runtime = root.resolve("runtime");
        Path dir = runtime.resolve(handle);
        if (!dir.isAbsolute() || !dir.normalize().equals(dir) || !dir.toString().equals(value))
            throw new IllegalStateException("invalid runtime directory");
        StructStat baseStat = Os.lstat(base.toString());
        if (!OsConstants.S_ISDIR(baseStat.st_mode) || baseStat.st_uid != Process.myUid())
            throw new IllegalStateException("unsafe application directory");
        for (Path path : new Path[] { root, runtime, dir }) {
            StructStat stat = Os.lstat(path.toString());
            if (!OsConstants.S_ISDIR(stat.st_mode) || stat.st_uid != Process.myUid() || (stat.st_mode & 07777) != 0700)
                throw new IllegalStateException("unsafe runtime directory");
        }
        return value;
    }
    static byte[] read(Context app, String profile, String handle, byte[] key) throws Exception {
        try { return new AndroidTailscaleStateStore(app).readStateBytes(profile, handle, key); }
        finally { if (key != null) Arrays.fill(key, (byte) 0); }
    }
    static void write(Context app, String profile, String handle, byte[] key, byte[] value) throws Exception {
        try { new AndroidTailscaleStateStore(app).writeStateBytes(profile, handle, key, value); }
        finally {
            if (key != null) Arrays.fill(key, (byte) 0);
            if (value != null) Arrays.fill(value, (byte) 0);
        }
    }
    static boolean isMissing(Throwable error) {
        return error != null && error.getClass() == AndroidTailscaleStateStore.StateKeyNotFoundException.class;
    }
}

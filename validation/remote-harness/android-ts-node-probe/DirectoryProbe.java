package org.herdr.network;

import android.content.Context;
import android.os.Process;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.nio.file.Path;
import org.json.JSONObject;

/** Read-only booleans; the real package-private directory callback is unchanged. */
public final class DirectoryProbe {
    public static JSONObject inspect(Context app, String profile, String handle) throws Exception {
        JSONObject out = new JSONObject();
        boolean prepared = false, callback = false;
        try { new AndroidTailscaleStateStore(app).runtimeDirectory(profile, handle); prepared = true; }
        catch (Exception expected) { }
        out.put("coreDirectoryPrepared", prepared);
        Path root = app.getNoBackupFilesDir().toPath().resolve("herdr-tailscale-state-v1");
        Path runtime = root.resolve("runtime");
        Path[] paths = {root, runtime, runtime.resolve(handle)};
        String[] labels = {"root", "runtime", "identity"};
        for (int i = 0; i < paths.length; i++) {
            JSONObject flags = new JSONObject();
            try {
                StructStat value = Os.lstat(paths[i].toString());
                flags.put("exists", true).put("directory", OsConstants.S_ISDIR(value.st_mode))
                    .put("ownerMatches", value.st_uid == Process.myUid())
                    .put("permissionBits0700", (value.st_mode & 0777) == 0700)
                    .put("fullMode0700", (value.st_mode & 07777) == 0700)
                    .put("setgid", (value.st_mode & 02000) != 0);
            } catch (Exception expected) {
                flags.put("exists", false);
            }
            out.put(labels[i], flags);
        }
        try { AndroidTailscaleConfig.directory(app, profile, handle); callback = true; }
        catch (Exception expected) { }
        out.put("productDirectoryCallbackSucceeded", callback);
        return out;
    }
}

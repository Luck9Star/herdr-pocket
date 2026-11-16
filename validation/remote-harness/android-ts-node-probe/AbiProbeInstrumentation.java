package org.herdr.network;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Locale;
import org.json.JSONObject;

/**
 * Separate-process ABI probe: hp_ts_node_new -&gt; hp_ts_node_status on the
 * same libhp_tailscale.so the product loads, driven with an in-memory store.
 * No Java StateStore callback and no Rust/JNI bridge are in the path, so the
 * result isolates whether the Go netmon getter can return at all on Android.
 *
 * It runs in its own instrumentation process: if the getter itself aborts,
 * this process dies and the main probe still records the bounded result.
 */
public final class AbiProbeInstrumentation extends Instrumentation {
    static {
        System.loadLibrary("abi_shim");
    }

    private static native int nativeRun(String libraryPath, String directory,
                                        String hostname, String controlUrl);

    @Override
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    private void writeResult(Context app, JSONObject report) throws Exception {
        File pending = new File(app.getFilesDir(), "ts-abi-probe-result.pending.json");
        Files.write(pending.toPath(), report.toString().getBytes(StandardCharsets.UTF_8));
        Files.move(pending.toPath(),
            new File(app.getFilesDir(), "ts-abi-probe-result.json").toPath(),
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,
            java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }

    @Override
    public void onStart() {
        Context app = getTargetContext().getApplicationContext();
        JSONObject report = new JSONObject();
        String profile = "0123456789abcdef0123456789abcdef";
        AndroidTailscaleStateStore store = null;
        AndroidTailscaleStateStore.Result identity = null;
        boolean passed = false;
        try {
            report.put("schemaVersion", 1);
            report.put("abiShimOk", false);
            // Identity evidence: the probe must run inside the target package
            // under its own UID, not under the instrumentation UID.
            report.put("targetPackage", app.getPackageName());
            report.put("uidMatches", app.getApplicationInfo().uid == android.os.Process.myUid());
            // Record this process' pid so the host can attribute a tombstone
            // to this probe process instead of the main probe's.
            try {
                Files.write(new File(app.getFilesDir(), "ts-abi-probe-pid.txt").toPath(),
                    String.valueOf(android.os.Process.myPid()).getBytes(StandardCharsets.UTF_8));
            } catch (Exception ignored) { }
            System.loadLibrary("hp_tailscale");
            report.put("librariesLoaded", true);
            // Deliberately no bindNative and no Rust runtime: this leg is
            // pure Java + C ABI, so the crash isolation stays meaningful.
            store = new AndroidTailscaleStateStore(app);
            identity = store.create(profile);
            report.put("identityCreated", identity.handle != null && !identity.handle.isEmpty());
            report.put("identityReadBack", store.status(profile) != null);
            // Opt-in marker: without it the Go side writes no diagnose file.
            boolean optIn = DirectoryProbe.enableNetmonDiagnose(app, profile, identity.handle);
            report.put("netmonOptIn", optIn);
            String directory = store.runtimeDirectory(identity.profileId, identity.handle);

            StringBuilder hostname = new StringBuilder("ts1:");
            for (byte value : MessageDigest.getInstance("SHA-256").digest(
                    ("herdr-tailscale-config-v1" + profile).getBytes(StandardCharsets.UTF_8)))
                hostname.append(String.format(Locale.ROOT, "%02x", value & 255));

            int code = nativeRun(
                app.getApplicationInfo().nativeLibraryDir + "/libhp_tailscale.so",
                directory, hostname.toString(), "https://controlplane.invalid");
            report.put("abiShimCode", code);
            report.put("abiShimOk", code == 0);

            // The status JSON is written beside the diagnose snapshot by the
            // shim; both survive this process.
            File statusFile = new File(directory, "hp-probe-abi-status.json");
            report.put("abiStatusFilePresent", statusFile.isFile());
            // Library evidence: dladdr's canonical path of hp_ts_node_new,
            // hashed and compared with the digest packed into the APK.
            File mappedFile = new File(directory, "hp-probe-abi-library.txt");
            report.put("mappedLibraryPresent", mappedFile.isFile());
            if (mappedFile.isFile()) {
                String mapped = new String(Files.readAllBytes(mappedFile.toPath()),
                    StandardCharsets.UTF_8).trim();
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    Files.readAllBytes(new File(mapped).toPath()));
                StringBuilder hex = new StringBuilder();
                for (byte value : digest) hex.append(String.format(Locale.ROOT, "%02x", value & 255));
                String packaged = new String(app.getAssets().open("hp-tailscale.sha256").readAllBytes(),
                    StandardCharsets.UTF_8).trim();
                report.put("libraryDigestMatches", hex.toString().equals(packaged));
            } else {
                report.put("libraryDigestMatches", false);
            }
            report.put("netmonDiagnose",
                DirectoryProbe.readNetmonDiagnose(app, profile, identity.handle));
            report.put("completed", true);
            passed = code == 0;
        } catch (Throwable error) {
            try { report.put("errClass", error.getClass().getSimpleName()); }
            catch (Exception ignored) { }
        } finally {
            try {
                if (identity != null && store != null) store.delete(identity.profileId, identity.handle);
            } catch (Exception ignored) { }
            try { writeResult(app, report); } catch (Exception ignored) { }
            Bundle result = new Bundle();
            result.putString("status", passed ? "passed" : "failed");
            finish(passed ? -1 : 0, result);
        }
    }
}

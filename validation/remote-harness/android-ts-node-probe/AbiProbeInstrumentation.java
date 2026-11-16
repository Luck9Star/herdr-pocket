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
                                        String hostname, String controlUrl,
                                        String evidenceDirectory, boolean startEngine);
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    private static void writeResult(Context app, JSONObject report) throws Exception {
        File pending = new File(app.getFilesDir(), "ts-abi-probe-result.pending.json");
        Files.write(pending.toPath(), report.toString().getBytes(StandardCharsets.UTF_8));
        Files.move(pending.toPath(),
            new File(app.getFilesDir(), "ts-abi-probe-result.json").toPath(),
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,
            java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }

    private static JSONObject readDiagnose(File nodeDir) throws Exception {
        File file = new File(nodeDir, "netmon-diagnose.json");
        if (!file.isFile()) return new JSONObject().put("fileMissing", true);
        try {
            return new JSONObject(new String(Files.readAllBytes(file.toPath()),
                StandardCharsets.UTF_8));
        } catch (Exception error) {
            return new JSONObject().put("parseError", true);
        }
    }

    @Override
    public void onStart() {
        Context app = getTargetContext().getApplicationContext();
        JSONObject report = new JSONObject();
        boolean passed = false;
        try {
            report.put("schemaVersion", 1);
            report.put("abiShimOk", false);
            // Identity evidence: the probe must run inside the target package
            // under its own UID, not under the instrumentation UID.
            report.put("targetPackage", app.getPackageName());
            report.put("uidMatches", app.getApplicationInfo().uid == android.os.Process.myUid());
            try {
                Files.write(new File(app.getFilesDir(), "ts-abi-probe-pid.txt").toPath(),
                    String.valueOf(android.os.Process.myPid()).getBytes(StandardCharsets.UTF_8));
            } catch (Exception ignored) { }
            // Deliberately no bindNative, no Java StateStore and no Rust
            // runtime: this leg is pure file I/O plus the product C ABI.

            // Fixed directories: the Go side writes the diagnose snapshot
            // into the config's directory and reads the opt-in marker from
            // that same directory. Both must survive an abort, so neither
            // may live under a random handle directory.
            File evidenceDir = new File(app.getFilesDir(), "hp-probe-abi");
            File nodeDir = new File(evidenceDir, "node");
            if (!nodeDir.isDirectory() && !nodeDir.mkdirs())
                throw new IllegalStateException("abi_node_dir_failed");
            File marker = new File(nodeDir, "netmon-diagnose.optin");
            if (!marker.exists() && !marker.createNewFile())
                throw new IllegalStateException("abi_marker_failed");
            report.put("netmonOptIn", true);

            StringBuilder hostname = new StringBuilder("ts1:");
            for (byte value : MessageDigest.getInstance("SHA-256").digest(
                    "herdr-tailscale-config-v1".getBytes(StandardCharsets.UTF_8)))
                hostname.append(String.format(Locale.ROOT, "%02x", value & 255));

            // Before any Go call: record the digest of the library this
            // process will load, so the mapping evidence has a counterpart
            // that survives an abort.
            String expectedLibrary = app.getApplicationInfo().nativeLibraryDir
                + "/libhp_tailscale.so";
            try {
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    Files.readAllBytes(new File(expectedLibrary).toPath()));
                StringBuilder hex = new StringBuilder();
                for (byte value : digest) hex.append(String.format(Locale.ROOT, "%02x", value & 255));
                Files.write(new File(evidenceDir, "hp-probe-abi-expected-digest.txt").toPath(),
                    hex.toString().getBytes(StandardCharsets.UTF_8));
            } catch (Exception error) {
                report.put("expectedDigestError", error.getClass().getSimpleName());
            }
            int code = nativeRun(expectedLibrary, nodeDir.getAbsolutePath(),
                hostname.toString(), "https://controlplane.invalid",
                evidenceDir.getAbsolutePath(), true);
            report.put("abiShimCode", code);
            report.put("abiShimOk", code == 0);

            // Store callback counters, mirrored into the fixed evidence
            // directory before the abort: they show whether the engine
            // reached the state store at all.
            File storeFile = new File(evidenceDir, "hp-probe-abi-store.txt");
            report.put("storeCountsPresent", storeFile.isFile());
            if (storeFile.isFile()) {
                for (String line : new String(Files.readAllBytes(storeFile.toPath()),
                        StandardCharsets.UTF_8).split("\n")) {
                    String[] parts = line.trim().split("=");
                    if (parts.length != 2) continue;
                    try {
                        int value = Integer.parseInt(parts[1]);
                        if (parts[0].equals("read")) report.put("storeReads", value);
                        else if (parts[0].equals("write")) report.put("storeWrites", value);
                        else if (parts[0].equals("start")) report.put("engineStartCode", value);
                    } catch (NumberFormatException ignored) { }
                }
            }

            File statusFile = new File(nodeDir, "hp-probe-abi-status.json");
            report.put("abiStatusFilePresent", statusFile.isFile());

            // dladdr records the canonical path before any Go call. Compare
            // both that path and its digest with this variant's artifact.
            File mappedFile = new File(evidenceDir, "hp-probe-abi-library.txt");
            report.put("mappedLibraryPresent", mappedFile.isFile());
            boolean pathMatches = false;
            boolean digestMatches = false;
            if (mappedFile.isFile()) {
                String mapped = new String(Files.readAllBytes(mappedFile.toPath()),
                    StandardCharsets.UTF_8).trim();
                pathMatches = mapped.equals(new File(expectedLibrary).getCanonicalPath());
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(
                    Files.readAllBytes(new File(mapped).toPath()));
                StringBuilder hex = new StringBuilder();
                for (byte value : digest) hex.append(String.format(Locale.ROOT, "%02x", value & 255));
                String packaged = new String(app.getAssets().open("hp-tailscale.sha256").readAllBytes(),
                    StandardCharsets.UTF_8).trim();
                digestMatches = hex.toString().equals(packaged);
            }
            report.put("mappedLibraryPathMatches", pathMatches);
            report.put("libraryDigestMatches", digestMatches);
            report.put("netmonDiagnose", readDiagnose(nodeDir));
            report.put("completed", true);
            passed = code == 0 && report.optBoolean("uidMatches")
                && pathMatches && digestMatches;
        } catch (Throwable error) {
            try { report.put("errClass", error.getClass().getSimpleName()); }
            catch (Exception ignored) { }
        } finally {
            try { writeResult(app, report); } catch (Exception ignored) { }
            Bundle result = new Bundle();
            result.putString("status", passed ? "passed" : "failed");
            finish(passed ? -1 : 0, result);
        }
    }
}

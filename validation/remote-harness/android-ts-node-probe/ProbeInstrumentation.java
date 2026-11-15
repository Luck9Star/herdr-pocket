package dev.herdr.tsnodeprobe;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;
import org.herdr.network.AndroidTailscaleConfig;
import org.herdr.network.AndroidTailscaleStateStore;
import org.herdr.network.DirectoryProbe;
import dev.herdr.pocket.NetworkRuntimeChannel;

/** Explicit local identity/start/status/stop only. Never invokes login or dial. */
public final class ProbeInstrumentation extends Instrumentation {
    private final JSONObject report = new JSONObject();
    private String stage = "initialization";
    private static final Set<String> STATES = new HashSet<>(Arrays.asList(
        "unavailable", "stopped", "starting", "engine-started", "needs-login", "needs-machine-auth", "running", "closing", "error"));
    private static final Set<String> ERRORS = new HashSet<>(Arrays.asList(
        "overlay_provider_unavailable", "mobile_node_binding_mismatch", "mobile_node_busy", "mobile_node_not_started",
        "network_scope_unavailable", "identity_unavailable", "invalid_network_request", "network_failed",
        "cancelled", "timeout", "timed_out", "close_pending", "state_store_unavailable"));

    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }

    private JSONObject call(long scope, String method, JSONObject arguments, String label) throws Exception {
        Object[] response = NetworkRuntimeChannel.nativeCall(scope, method, arguments.toString(), null);
        if (response == null || response.length != 2 || !(response[0] instanceof String) || response[1] != null)
            throw new IllegalStateException();
        JSONObject envelope = new JSONObject((String) response[0]);
        report.put(label + "Ok", envelope.optBoolean("ok", false));
        if (!envelope.optBoolean("ok", false)) {
            String error = envelope.optString("error", "");
            report.put(label + "Error", ERRORS.contains(error) ? error : "other_product_error");
            return new JSONObject();
        }
        JSONObject value = envelope.getJSONObject("value");
        String state = value.optString("state", "");
        if (!state.isEmpty()) report.put(label + "State", STATES.contains(state) ? state : "other_state");
        return value;
    }

    @Override public void onStart() {
        Context app = getTargetContext().getApplicationContext();
        long scope = 0;
        JSONObject binding = null;
        AndroidTailscaleStateStore store = null;
        AndroidTailscaleStateStore.Result identity = null;
        try {
            report.put("schemaVersion", 1).put("loginInvoked", false).put("dialInvoked", false);
            stage = "private-config";
            JSONObject config = new JSONObject(Files.readString(new File(app.getFilesDir(), "ts-node-probe-config.json").toPath()));
            String control = config.getString("controlUrl"), hostname = "android-synthetic-probe";
            if (!control.matches("https://127\\.0\\.0\\.1:[0-9]+")) throw new IllegalStateException();
            stage = "load-libraries";
            System.loadLibrary("heeler_easytier");
            System.loadLibrary("hp_tailscale");
            System.loadLibrary("herdr_flutter_network_runtime");
            report.put("librariesLoaded", true);
            stage = "bind-java-context";
            report.put("contextBound", AndroidTailscaleConfig.bindNative(app));
            if (!report.getBoolean("contextBound")) throw new IllegalStateException();
            stage = "create-identity";
            store = new AndroidTailscaleStateStore(app);
            String profile = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
            identity = store.create(profile);
            report.put("identityCreated", identity != null).put("identityReadBack", store.status(profile) != null);
            stage = "directory-callback";
            report.put("directories", DirectoryProbe.inspect(app, profile, identity.handle));
            StringBuilder hash = new StringBuilder("ts1:");
            for (byte value : MessageDigest.getInstance("SHA-256").digest(
                    ("herdr-tailscale-config-v1\u0000" + control + "\u0000" + hostname).getBytes(StandardCharsets.UTF_8)))
                hash.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            binding = new JSONObject().put("provider", "tailscale").put("profileId", profile)
                .put("profileRevision", 1).put("networkName", hash.toString()).put("identityRef", identity.handle);
            stage = "create-native-scope";
            scope = NetworkRuntimeChannel.nativeCreateScope();
            report.put("nativeScopeCreated", scope > 0);
            if (scope <= 0) throw new IllegalStateException();
            stage = "native-available";
            JSONObject available = call(scope, "available", new JSONObject().put("provider", "tailscale"), "available");
            report.put("providerAvailable", available.optBoolean("available", false));
            stage = "native-start";
            call(scope, "nodeStart", new JSONObject().put("binding", binding).put("settings",
                new JSONObject().put("controlUrl", control).put("hostname", hostname)), "start");
            stage = "native-status";
            JSONArray states = new JSONArray();
            boolean needsLogin = false;
            long deadline = android.os.SystemClock.elapsedRealtime() + 15000;
            while (android.os.SystemClock.elapsedRealtime() < deadline) {
                JSONObject value = call(scope, "nodeStatus", new JSONObject().put("profileId", profile).put("provider", "tailscale"), "status");
                String state = value.optString("state", "");
                String safe = STATES.contains(state) ? state : "other_state";
                if (states.length() == 0 || !states.getString(states.length() - 1).equals(safe)) states.put(safe);
                if (state.equals("needs-login")) { needsLogin = true; break; }
                if (states.length() > 16 || !report.optBoolean("startOk")) break;
                android.os.SystemClock.sleep(100);
            }
            report.put("states", states).put("needsLoginReached", needsLogin);
            report.put("passed", needsLogin && report.optBoolean("startOk"));
        } catch (Throwable error) {
            try { report.put("passed", false).put("failureStage", stage)
                .put("failureClass", error instanceof LinkageError ? "linkage" : error instanceof SecurityException ? "security" : "controlled_failure"); }
            catch (Exception ignored) { }
        } finally {
            try {
                if (scope > 0 && binding != null) {
                    call(scope, "nodeStop", new JSONObject().put("binding", binding), "stop");
                    JSONObject closed = new JSONObject(NetworkRuntimeChannel.nativeCloseScope(scope));
                    report.put("nativeScopeClosed", closed.optBoolean("ok", false));
                }
                if (store != null && identity != null && report.optBoolean("stopOk") && "stopped".equals(report.optString("stopState"))) {
                    store.delete(identity.profileId, identity.handle);
                    report.put("identityDeleted", store.status(identity.profileId) == null);
                }
            } catch (Throwable error) { try { report.put("cleanupFailed", true); } catch (Exception ignored) { } }
            try {
                report.put("lastStage", stage);
                report.put("passed", report.optBoolean("passed") && report.optBoolean("stopOk")
                    && "stopped".equals(report.optString("stopState")) && report.optBoolean("nativeScopeClosed")
                    && report.optBoolean("identityDeleted") && !report.optBoolean("cleanupFailed"));
                Files.writeString(new File(app.getFilesDir(), "ts-node-probe-result.json").toPath(), report.toString());
            } catch (Exception ignored) { }
            Bundle result = new Bundle(); result.putString("status", report.optBoolean("passed") ? "passed" : "failed");
            finish(report.optBoolean("passed") ? -1 : 0, result);
        }
    }
}

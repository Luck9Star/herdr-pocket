package org.herdr.network;

import android.app.Instrumentation;
import android.os.Bundle;

/**
 * Minimal instrumentation runner with no test-framework dependency. Streams one
 * status line per event through the instrumentation protocol so
 * {@code adb shell am instrument -w} output is self-describing, then finishes
 * with an explicit HERDR_KEYSTORE_RESULT line and the evidence JSON. A failure
 * keeps the failing check and stack trace in the same output stream.
 */
public final class ZeroTierAndroidKeyStoreInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        start();
    }

    @Override public void onStart() {
        super.onStart();
        String evidence=null;
        Throwable failure=null;
        try {
            evidence=ZeroTierAndroidKeyStoreTest.run(getTargetContext(), this::stream);
        } catch (Throwable error) { failure=error; }
        if (failure==null) {
            stream("HERDR_KEYSTORE_EVIDENCE "+evidence);
            stream("HERDR_KEYSTORE_RESULT PASS");
        } else {
            stream("HERDR_KEYSTORE_FAIL "+failure);
            for (StackTraceElement at : failure.getStackTrace()) stream("  at "+at);
            stream("HERDR_KEYSTORE_RESULT FAIL");
        }
        Bundle results=new Bundle();
        results.putString("stream", failure==null ? "HERDR_KEYSTORE_RESULT PASS"
            : "HERDR_KEYSTORE_RESULT FAIL: "+failure);
        finish(failure==null ? 0 : 1, results);
    }
    private void stream(String message) {
        Bundle status=new Bundle();
        status.putString("stream", message);
        sendStatus(0, status);
    }
}

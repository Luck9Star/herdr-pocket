package org.herdr.tlsprobe;

import android.app.Instrumentation;
import android.os.Bundle;
import android.os.Process;

/** Disposable instrumentation only; no credentials, UI or system trust changes. */
public final class ProbeInstrumentation extends Instrumentation {
    private Bundle args;
    private static native int probe(int port, boolean wrongHost);
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        args = arguments;
        start();
    }
    @Override public void onStart() {
        int code = 99;
        int wrong = 99;
        try {
            int port = Integer.parseInt(args.getString("port", "0"));
            if (port < 1 || port > 65535) throw new IllegalArgumentException();
            System.loadLibrary("hptlsprobe");
            code = probe(port, false);
            if (code == 0) wrong = probe(port, true);
        } catch (Throwable ignored) {
            code = 99;
        }
        Bundle result = new Bundle();
        result.putString("stream", "HP_TLS_RESULT pid=" + Process.myPid() + " code=" + code + " wrong=" + wrong + "\n");
        finish(0, result);
    }
}

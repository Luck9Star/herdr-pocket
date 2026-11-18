package org.herdr.tlsprobe;

import android.app.Instrumentation;
import android.os.Bundle;
import android.os.Process;
import java.io.File;

/** Disposable instrumentation only; no credentials, UI or system trust changes. */
public final class ProbeInstrumentation extends Instrumentation {
    private Bundle args;
    private static native int prepare();
    private static native int probe(int port, boolean wrongHost);
    @Override public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        args = arguments;
        start();
    }
    @Override public void onStart() {
        int code = 99;
        int wrong = 99;
        int prep = 99;
        try {
            int port = Integer.parseInt(args.getString("port", "0"));
            if (port < 1 || port > 65535) throw new IllegalArgumentException();
            System.loadLibrary("hptlsprobe");
            prep = prepare();
            if (prep == 1 || prep == 2) code = probe(port, false);
            if (code == 0) wrong = probe(port, true);
        } catch (Throwable ignored) {
            code = 99;
        }
        File wrapper = new File(getTargetContext().getApplicationInfo().nativeLibraryDir, "wrap.sh");
        boolean wrapExists = wrapper.isFile();
        boolean wrapExecutable = wrapper.canExecute();
        boolean javaEnvironment = "/data/user/0/org.herdr.tlsprobe/files/ca.pem".equals(System.getenv("SSL_CERT_FILE"))
                && "/data/user/0/org.herdr.tlsprobe/files/empty-ca".equals(System.getenv("SSL_CERT_DIR"));
        Bundle result = new Bundle();
        result.putString("stream", "HP_TLS_RESULT pid=" + Process.myPid() + " code=" + code + " wrong=" + wrong + " prep=" + prep + " wrap=" + (wrapExists ? 1 : 0) + " executable=" + (wrapExecutable ? 1 : 0) + " javaEnv=" + (javaEnvironment ? 1 : 0) + "\n");
        finish(0, result);
    }
}

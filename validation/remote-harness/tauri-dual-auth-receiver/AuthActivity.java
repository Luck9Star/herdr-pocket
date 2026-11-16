package dev.herdrpocket.dualtestauth;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.Gravity;
import android.view.WindowInsets;
import android.graphics.Insets;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.nio.charset.StandardCharsets;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/** Disposable explicit consent receiver; never opens arbitrary network URLs. */
public final class AuthActivity extends Activity {
    private Button approval;
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus && approval != null && approval.isEnabled()) approval.requestFocusFromTouch();
    }
    static String readExpectedPort(File root) throws IOException {
        byte[] bytes = new byte[6];
        int count = 0;
        try (FileInputStream input = new FileInputStream(new File(root, "port"))) {
            while (count < bytes.length) {
                int read = input.read(bytes, count, bytes.length - count);
                if (read < 0) break;
                if (read == 0) throw new IOException();
                count += read;
            }
        }
        if (count < 1 || count > 5) throw new IOException();
        String port = new String(bytes, 0, count, StandardCharsets.US_ASCII);
        if (!port.matches("[1-9][0-9]{0,4}") || Integer.parseInt(port) > 65535) throw new IOException();
        return port;
    }
    static void writeApprovedUrl(File root, byte[] bytes) throws IOException {
        if (bytes.length < 1 || bytes.length > 4096) throw new IOException();
        try (FileOutputStream output = new FileOutputStream(new File(root, "approved-url"))) {
            output.write(bytes);
        }
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        final int padding = Math.round(24 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);
        layout.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override public WindowInsets onApplyWindowInsets(View view, WindowInsets insets) {
                Insets safe = insets.getInsets(WindowInsets.Type.systemBars() |
                        WindowInsets.Type.displayCutout() | WindowInsets.Type.systemGestures());
                view.setPadding(padding + safe.left, padding + safe.top,
                        padding + safe.right, padding + safe.bottom);
                return insets;
            }
        });
        TextView source = new TextView(this);
        source.setGravity(Gravity.CENTER);
        source.setContentDescription("dual_auth_origin");
        layout.addView(source);
        TextView status = new TextView(this);
        status.setGravity(Gravity.CENTER);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        layout.addView(status);
        Button approve = new Button(this);
        approval = approve;
        approve.setText("批准本次测试授权");
        approve.setContentDescription("dual_auth_approve");
        approve.setMinimumHeight(Math.round(56 * getResources().getDisplayMetrics().density));
        approve.setFocusable(true);
        approve.setFocusableInTouchMode(true);
        approve.setEnabled(false);
        layout.addView(approve);
        setContentView(layout);
        layout.requestApplyInsets();
        try {
            Intent intent = getIntent();
            Uri url = intent.getData();
            File root = getFilesDir();
            String expectedPort = readExpectedPort(root);
            if (!Intent.ACTION_VIEW.equals(intent.getAction()) || url == null ||
                !"https".equals(url.getScheme()) || !"127.0.0.1".equals(url.getHost()) ||
                !expectedPort.matches("[1-9][0-9]{0,4}") || url.getPort() != Integer.parseInt(expectedPort) ||
                url.getUserInfo() != null || url.getFragment() != null || url.toString().length() > 4096) throw new IllegalArgumentException();
            byte[] approvedUrl = url.toString().getBytes(StandardCharsets.UTF_8);
            if (approvedUrl.length > 4096) throw new IllegalArgumentException();
            source.setText("隔离测试控制面：127.0.0.1:" + expectedPort);
            status.setText("请审查本次隔离测试授权并明确同意");
            status.setContentDescription("ready");
            approve.setEnabled(true);
            approve.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View view) {
                    if (!approve.isEnabled()) return;
                    approve.setEnabled(false);
                    status.setText("测试授权同意已接收");
                    status.setContentDescription("click_received");
                    try {
                        writeApprovedUrl(root, approvedUrl);
                        status.setText("测试授权已交接");
                        status.setContentDescription("delivered");
                    } catch (Exception ignored) {
                        status.setText("测试授权交接失败");
                        status.setContentDescription("delivery_failed");
                    }
                }
            });
            approve.requestFocusFromTouch();
        } catch (Exception ignored) {
            status.setText("测试授权来源不匹配");
            status.setContentDescription("source_mismatch");
        }
    }
}

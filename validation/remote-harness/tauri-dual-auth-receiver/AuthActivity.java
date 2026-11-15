package dev.herdrpocket.dualtestauth;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/** Disposable explicit consent receiver; never opens arbitrary network URLs. */
public final class AuthActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        TextView status = new TextView(this);
        layout.addView(status);
        Button approve = new Button(this);
        approve.setText("批准本次测试授权");
        approve.setEnabled(false);
        layout.addView(approve);
        setContentView(layout);
        try {
            Intent intent = getIntent();
            Uri url = intent.getData();
            Path root = getFilesDir().toPath();
            String expectedPort = Files.readString(root.resolve("port"), StandardCharsets.US_ASCII).trim();
            if (!Intent.ACTION_VIEW.equals(intent.getAction()) || url == null ||
                !"https".equals(url.getScheme()) || !"127.0.0.1".equals(url.getHost()) ||
                !expectedPort.matches("[1-9][0-9]{0,4}") || url.getPort() != Integer.parseInt(expectedPort) ||
                url.getUserInfo() != null || url.toString().length() > 4096) throw new IllegalArgumentException();
            status.setText("隔离测试控制面：127.0.0.1:" + expectedPort);
            approve.setEnabled(true);
            approve.setOnClickListener(v -> {
                try {
                    Files.writeString(root.resolve("approved-url"), url.toString(), StandardCharsets.UTF_8);
                    status.setText("测试授权已交接");
                    approve.setEnabled(false);
                } catch (Exception ignored) { status.setText("测试授权交接失败"); }
            });
        } catch (Exception ignored) { status.setText("测试授权来源不匹配"); }
    }
}

package org.herdr.pairing.camera;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import com.google.zxing.client.android.Intents;
import com.journeyapps.barcodescanner.ScanOptions;
import java.nio.charset.StandardCharsets;

/** A scan returns public text for the response preview. It grants no authorization. */
public final class PairScan {
    private PairScan() {}
    public static Intent intent(Context context) {
        return new ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
            .setBarcodeImageEnabled(false).setBeepEnabled(false)
            .setPrompt("扫描主机配对响应").createScanIntent(context);
    }
    public static String result(int code, Intent data) {
        if (code != Activity.RESULT_OK || data == null) {
            if (data != null && data.getBooleanExtra(Intents.Scan.MISSING_CAMERA_PERMISSION, false))
                throw new IllegalStateException("camera_permission_denied");
            throw new IllegalStateException("scan_cancelled");
        }
        String text = data.getStringExtra(Intents.Scan.RESULT);
        if (text == null || text.isEmpty() || text.length() > 2048 || text.getBytes(StandardCharsets.UTF_8).length > 2048)
            throw new IllegalStateException("invalid_public_response");
        return text;
    }
}

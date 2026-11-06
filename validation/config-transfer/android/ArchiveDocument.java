package org.herdr.pocket.transfer;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Intent;
import android.net.Uri;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Exchanges encrypted files only through a location chosen by the user. */
public final class ArchiveDocument {
    public static final int MAX_BYTES = 34 + 65536 + 16;
    private ArchiveDocument() {}

    public static Intent choose(boolean save) {
        Intent intent = new Intent(save ? Intent.ACTION_CREATE_DOCUMENT : Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType(save ? "application/octet-stream" : "*/*");
        if (save) intent.putExtra(Intent.EXTRA_TITLE, "herdr-pocket.hpkt");
        return intent;
    }

    public static void checkForSave(byte[] archive) throws IOException {
        if (archive == null || archive.length < 51 || archive.length > MAX_BYTES ||
                archive[0] != 'H' || archive[1] != 'P' || archive[2] != 'K' || archive[3] != 'T' ||
                archive[4] != 1 || archive[5] != 1) {
            throw new IOException("invalid_archive");
        }
    }

    public static Uri selectedUri(int result, Intent data) throws IOException {
        if (result == Activity.RESULT_CANCELED) return null;
        Uri uri = data == null ? null : data.getData();
        if (result != Activity.RESULT_OK || uri == null || !ContentResolver.SCHEME_CONTENT.equals(uri.getScheme())) {
            throw new IOException("invalid_document");
        }
        return uri;
    }

    public static byte[] read(ContentResolver resolver, Uri uri) throws IOException {
        try (InputStream input = resolver.openInputStream(uri)) {
            if (input == null) throw new IOException("document_unavailable");
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int count;
            while ((count = input.read(chunk)) != -1) {
                if (count == 0 || output.size() + count > MAX_BYTES) throw new IOException("invalid_size");
                output.write(chunk, 0, count);
            }
            return output.toByteArray();
        }
    }

    public static void write(ContentResolver resolver, Uri uri, byte[] archive) throws IOException {
        checkForSave(archive);
        try (OutputStream output = resolver.openOutputStream(uri, "wt")) {
            if (output == null) throw new IOException("document_unavailable");
            output.write(archive);
            output.flush();
        }
    }
}

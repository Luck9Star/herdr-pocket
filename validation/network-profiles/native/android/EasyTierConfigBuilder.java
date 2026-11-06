package org.herdr.network;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Fixed, bounded TOML writer. No arbitrary keys or prebuilt TOML are accepted. */
final class EasyTierConfigBuilder {
    static final int MAX_CONFIG = 64 * 1024;
    static final class Input {
        final String name;
        final String[] peers;
        Input(String name, String[] peers) { this.name = name; this.peers = peers; }
    }
    static Input validate(String name, String[] peers) {
        if (name == null || name.isEmpty()) throw invalid();
        boolean hasText = false;
        for (int i = 0; i < name.length();) {
            int cp = name.codePointAt(i);
            if ((cp >= 0xd800 && cp <= 0xdfff) || cp <= 0x1f || (cp >= 0x7f && cp <= 0x9f)) throw invalid();
            if (!Character.isWhitespace(cp) && !Character.isSpaceChar(cp)) hasText = true;
            i += Character.charCount(cp);
        }
        if (!hasText || name.getBytes(StandardCharsets.UTF_8).length > 64 || peers == null || peers.length < 1 || peers.length > 16) throw invalid();
        String[] copy = peers.clone(); Set<String> seen = new HashSet<>();
        for (String peer : copy) {
            if (peer == null || peer.isEmpty() || peer.length() > 2048 || !seen.add(peer)) throw invalid();
            for (int i = 0; i < peer.length(); i++) {
                char c = peer.charAt(i);
                if (c < 0x21 || c > 0x7e || c == '\\' || c == '?' || c == '#') throw invalid();
            }
            try {
                URI uri = new URI(peer);
                String scheme = uri.getScheme(), authority = uri.getRawAuthority();
                if (!("tcp".equals(scheme) || "udp".equals(scheme) || "ws".equals(scheme) || "wss".equals(scheme)) ||
                    authority == null || uri.getHost() == null || uri.getHost().isEmpty() || authority.contains("@") ||
                    authority.endsWith(":") || uri.getRawQuery() != null || uri.getRawFragment() != null) throw invalid();
                int port = uri.getPort();
                if (port == 0 || port > 65535) throw invalid();
                if (("tcp".equals(scheme) || "udp".equals(scheme)) &&
                    (port < 1 || !(uri.getRawPath().isEmpty() || "/".equals(uri.getRawPath())))) throw invalid();
            } catch (java.net.URISyntaxException e) { throw invalid(); }
        }
        return new Input(name, copy);
    }
    private static IllegalArgumentException invalid() { return new IllegalArgumentException("invalid_network_profile"); }
    static byte[] build(Input input, String instanceId, byte[] secret) {
        NetworkSecretStoreCore.checkedHandle(instanceId);
        if (secret == null || secret.length == 0 || secret.length > NetworkSecretStoreCore.MAX_SECRET_BYTES) throw new IllegalArgumentException("invalid secret");
        Writer out = new Writer();
        try {
            out.ascii("instance_id = "); out.quoted(instanceId.getBytes(StandardCharsets.UTF_8));
            out.ascii("\ndhcp = true\nlisteners = []\n[network_identity]\nnetwork_name = ");
            out.quoted(input.name.getBytes(StandardCharsets.UTF_8));
            out.ascii("\nnetwork_secret = "); out.quoted(secret);
            for (String peer : input.peers) {
                out.ascii("\n[[peer]]\nuri = "); out.quoted(peer.getBytes(StandardCharsets.UTF_8));
            }
            out.ascii("\n[flags]\nno_tun = true\n");
            return Arrays.copyOf(out.buffer, out.length);
        } finally { Arrays.fill(out.buffer, (byte) 0); }
    }
    private static final class Writer {
        final byte[] buffer = new byte[MAX_CONFIG]; int length;
        void put(int value) {
            if (length == buffer.length) throw new IllegalArgumentException("config too large");
            buffer[length++] = (byte) value;
        }
        void ascii(String text) { for (int i = 0; i < text.length(); i++) put(text.charAt(i)); }
        void quoted(byte[] value) {
            put('"');
            for (int i = 0; i < value.length; i++) {
                int c = value[i] & 0xff;
                if (c == '"' || c == '\\') { put('\\'); put(c); }
                else if (c < 0x20 || c == 0x7f) hexEscape(c);
                else if (c == 0xc2 && i + 1 < value.length && (value[i+1] & 0xff) >= 0x80 && (value[i+1] & 0xff) <= 0x9f) {
                    hexEscape(value[++i] & 0xff);
                } else put(c);
            }
            put('"');
        }
        void hexEscape(int c) {
            String hex = "0123456789abcdef";
            ascii("\\u00"); put(hex.charAt(c >>> 4)); put(hex.charAt(c & 15));
        }
    }
}

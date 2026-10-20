package com.klab.lapis.stub;

import java.io.ByteArrayOutputStream;
import java.security.MessageDigest;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/** Minimal HTTP/1.1 GET server with single-range support, mirroring resource_service paths. */
public class HttpFileServer {
    final int port;
    final ProtobufCore core;
    final boolean assetMode;
    ServerSocket ss;
    volatile boolean run = true;

    public HttpFileServer(int port, ProtobufCore core) {
        this.port = port; this.core = core;
        this.assetMode = ProtobufCore.isHostPackage(core.ctx.getPackageName());
    }

    public void start() throws Exception {
        ss = new ServerSocket(port, 64, java.net.InetAddress.getByName("0.0.0.0"));
        Thread t = new Thread(() -> {
            while (run) {
                try {
                    Socket c = ss.accept();
                    Thread h = new Thread(() -> handle(c));
                    h.setDaemon(true);
                    h.start();
                } catch (Exception e) { if (run) break; }
            }
        });
        t.setDaemon(true);
        t.start();
        L.log(null, "http listening " + port);
    }

    public void stop() throws Exception { run = false; ss.close(); }

    void handle(Socket c) {
        try {
            c.setSoTimeout(10000);
            byte[] buf = new byte[8192];
            int n = c.getInputStream().read(buf);
            if (n <= 0) { c.close(); return; }
            String head = new String(buf, 0, n, StandardCharsets.UTF_8);
            String[] lines = head.split("\r\n");
            String[] req = lines[0].split(" ");
            String method = req[0], path = req[1];
            String range = null;
            for (String l : lines) {
                if (l.toLowerCase().startsWith("range:")) range = l.substring(6).trim();
            }
            if (path.contains("?")) path = path.substring(0, path.indexOf('?'));
            path = java.net.URLDecoder.decode(path, "UTF-8");

            File f = resolve(path);
            if (f == null || !f.isFile()) {
                // On a fresh install the client can ask for the master tables before Seed.pass has
                // put them on the tree, and a 404 there costs a retry round (observed 8x) while the
                // game waits. The APK carries both tables, so serve the packaged copy instead.
                if (assetPath(path) != null) { handleAsset(c, method, path, range); return; }
            }
            L.log(null, (f != null && f.isFile() ? "200 " : "404 ") + method + " " + path + (range != null ? " range" : ""));
            if (f == null || !f.isFile()) {
                c.getOutputStream().write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n".getBytes(StandardCharsets.UTF_8));
                c.close(); return;
            }
            long size = f.length(), start = 0, end = size - 1;
            boolean partial = false;
            if (range != null && range.startsWith("bytes=")) {
                String[] rr = range.substring(6).split("-");
                try { start = Long.parseLong(rr[0].trim()); } catch (Exception ignored) {}
                if (rr.length > 1 && !rr[1].trim().isEmpty()) try { end = Long.parseLong(rr[1].trim()); } catch (Exception ignored) {}
                if (start > end || start >= size) {
                    c.getOutputStream().write(("HTTP/1.1 416 Range Not Satisfiable\r\nContent-Range: bytes */" + size + "\r\nContent-Length: 0\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                    c.close(); return;
                }
                partial = true;
            }
            long len = end - start + 1;
            OutputStream os = c.getOutputStream();
            StringBuilder h = new StringBuilder();
            h.append(partial ? "HTTP/1.1 206 Partial Content\r\n" : "HTTP/1.1 200 OK\r\n");
            h.append("Content-Type: application/octet-stream\r\n");
            h.append("Accept-Ranges: bytes\r\n");
            h.append("Content-Length: ").append(len).append("\r\n");
            if (partial) h.append("Content-Range: bytes ").append(start).append('-').append(end).append('/').append(size).append("\r\n");
            h.append("\r\n");
            os.write(h.toString().getBytes(StandardCharsets.UTF_8));
            InputStream in = new FileInputStream(f);
            in.skip(start);
            byte[] b = new byte[65536];
            long remain = len;
            while (remain > 0) {
                int r = in.read(b, 0, (int) Math.min(b.length, remain));
                if (r <= 0) break;
                os.write(b, 0, r);
                remain -= r;
            }
            in.close();
            os.flush();
            c.close();
        } catch (Exception e) {
            try { c.close(); } catch (Exception ignored) {}
        }
    }

    static java.util.HashMap<String,String> nameToSha1 = new java.util.HashMap<>();
    static java.util.HashMap<String,String> sha1ToFile = new java.util.HashMap<>();
    /** extract all "key":"value" pairs from a flat JSON object string */
    static void extractPairs(String js, java.util.HashMap<String,String> out) {
        int i = 0;
        while (true) {
            int q1 = js.indexOf('"', i); if (q1 < 0) return;
            int q2 = js.indexOf('"', q1 + 1); if (q2 < 0) return;
            int colon = js.indexOf(':', q2 + 1); if (colon < 0) return;
            int j = colon + 1;
            while (j < js.length() && Character.isWhitespace(js.charAt(j))) j++;
            if (j >= js.length() || js.charAt(j) != '"') { i = q2 + 1; continue; }
            int q3 = js.indexOf('"', j + 1); if (q3 < 0) return;
            out.put(js.substring(q1 + 1, q2), js.substring(j + 1, q3));
            i = q3 + 1;
        }
    }
    static void loadLookup(android.content.Context c) {
        try {
            java.io.InputStream in = c.getAssets().open("name_sha1.json");
            String js = readAll(in); in.close();
            extractPairs(js, nameToSha1);
            in = c.getAssets().open("sha1_file.json");
            js = readAll(in); in.close();
            extractPairs(js, sha1ToFile);
            L.log("lookup tables: names=" + nameToSha1.size() + " files=" + sha1ToFile.size());
        } catch (Throwable t) { L.log("lookup load failed: " + t); }
    }
    static String readAll(java.io.InputStream in) throws Exception {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192]; int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toString("UTF-8");
    }
    /** logical package path (e.g. assets/products/resources) -> physical file via sha1 tables */
    File resolveBySha1(String path) {
        try {
            int i = path.indexOf("/AssetBundles/");
            if (i < 0) return null;
            String rel = path.substring(i + 14);
            if (rel.endsWith(".bdl")) rel = rel.substring(0, rel.length() - 4);
            String sha1 = nameToSha1.get(rel);
            if (sha1 == null) return null;
            String fname = sha1ToFile.get(sha1);
            if (fname == null) return null;
            File root = new File(core.resRoot, "JP/AssetBundles");
            if (!root.isDirectory()) root = new File(core.resRoot, "AssetBundles");
            File f = new File(root, fname);
            if (f.isFile()) return f;
            File r2 = new File(new File(core.resRoot, "server"), "JP/AssetBundles");
            f = new File(r2, fname);
            return f.isFile() ? f : null;
        } catch (Throwable t) { return null; }
    }
    File resolve(String path0) {
        String path = path0.replaceAll("/{2,}", "/");
        // CDN convention: /<resVersion>/Android/JP/... -> strip the version segment
        if (path.matches("^/[0-9]{12}-[0-9]-[0-9a-f]{4,16}/.*")) {
            int slash = path.indexOf('/', 1);
            if (slash > 0) path = path.substring(slash);
        }
        File root = new File(core.resRoot, "server");
        if (!root.isDirectory()) root = core.resRoot;
        if (path.endsWith(".hash")) {
            // dynamic SHA1 sidecar: <X>.hash served as uppercase hex of sha1(X) if no static file exists
            String base = path.substring(0, path.length() - 5);
            File bf = resolve(base);
            if (bf != null && bf.isFile()) return hashSidecar(bf);
        }
        if (path.endsWith("/Android/JP/manifest.xml")) return new File(root, "manifest.xml");
        if (path.contains("/AssetBundles/")) {
            String rel = path.substring(path.indexOf("/AssetBundles/") + "/AssetBundles/".length());
            if (rel.contains("..") || rel.contains("\\")) return null;
            return probe(new File(root, "JP/AssetBundles"), rel);
        }
        if (path.contains("/SoundBanks/")) {
            String rel = path.substring(path.indexOf("/SoundBanks/") + "/SoundBanks/".length());
            if (rel.contains("..") || rel.contains("\\")) return null;
            return probe(new File(root, "SoundBanks"), rel);
        }
        if (path.endsWith("/MasterData/master_data.db")) return new File(root, "MasterData/master_data.db");
        if (path.endsWith("/Android/JP/master_data_lang.db")) return new File(root, "JP/master_data_lang.db");
        if (nameToSha1 != null) { File f = resolveBySha1(path); if (f != null) return f; }
        return null;
    }

    // ---- asset mode (merged APK): serve from assets/res/** via AssetManager ----
    void handleAsset(Socket c, String method, String path, String range) {
        try {
            String ap = assetPath(path);
            L.log(null, (ap == null ? "404 " : "200 ") + method + " " + path);
            if (ap == null) {
                c.getOutputStream().write(("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n").getBytes(StandardCharsets.UTF_8));
                c.close(); return;
            }
            long start = 0, total;
            InputStream in;
            if (ap.startsWith("hash:")) {
                byte[] hb = core.sha1HexAsset(ap.substring(5)).getBytes("UTF-8");
                total = hb.length;
                byte[] head = ("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: " + total + "\r\n\r\n").getBytes(StandardCharsets.UTF_8);
                OutputStream os = c.getOutputStream();
                os.write(head); os.write(hb); os.flush(); c.close(); return;
            }
            in = core.ctx.getAssets().open(ap);
            total = in.available();
            if (range != null && range.startsWith("bytes=")) {
                String[] rr = range.substring(6).split("-");
                try { start = Long.parseLong(rr[0].trim()); } catch (Exception ignored) {}
                long skip = start;
                while (skip > 0) { long s2 = in.skip(skip); if (s2 <= 0) break; skip -= s2; }
            }
            OutputStream os = c.getOutputStream();
            byte[] head = ("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nAccept-Ranges: bytes\r\nContent-Length: " + (total - start) + "\r\n\r\n").getBytes(StandardCharsets.UTF_8);
            os.write(head);
            byte[] b = new byte[65536]; int n;
            while ((n = in.read(b)) > 0) os.write(b, 0, n);
            in.close(); os.flush(); c.close();
        } catch (Exception e) {
            try { c.getOutputStream().write(("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n").getBytes(StandardCharsets.UTF_8)); } catch (Exception ignored) {}
            try { c.close(); } catch (Exception ignored) {}
        }
    }

    String assetPath(String path) {
        if (path.endsWith("/Android/JP/manifest.xml")) return "stub/manifest.xml";
        if (path.endsWith(".hash")) {
            String base = assetPath(path.substring(0, path.length() - 5));
            return base == null ? null : "hash:" + base;
        }
        if (path.contains("/AssetBundles/")) {
            String rel = path.substring(path.indexOf("/AssetBundles/") + 14);
            if (rel.contains("..")) return null;
            return "res/JP/AssetBundles/" + rel;
        }
        if (path.contains("/SoundBanks/")) {
            String rel = path.substring(path.indexOf("/SoundBanks/") + 12);
            if (rel.contains("..")) return null;
            return "res/SoundBanks/" + rel;
        }
        if (path.endsWith("/MasterData/master_data.db")) return "res/MasterData/master_data.db";
        if (path.endsWith("/Android/JP/master_data_lang.db")) return "res/JP/master_data_lang.db";
        return null;
    }

    File hashSidecar(File f) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-1");
            InputStream in = new FileInputStream(f);
            byte[] b = new byte[65536]; int n;
            while ((n = in.read(b)) > 0) md.update(b, 0, n);
            in.close();
            StringBuilder sb = new StringBuilder();
            for (byte x : md.digest()) sb.append(String.format("%02X", x));
            File out = new File(f.getParentFile(), f.getName() + ".hash.gen");
            java.io.FileOutputStream fos = new java.io.FileOutputStream(out);
            fos.write(sb.toString().getBytes("UTF-8")); fos.close();
            out.deleteOnExit();
            return out;
        } catch (Exception e) { return null; }
    }

    File probe(File base, String rel) {
        File f = new File(base, rel);
        if (f.isFile()) return f;
        return null;
    }
}

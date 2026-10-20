package com.klab.lapis.stub;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.security.KeyStore;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLServerSocketFactory;
import javax.net.ssl.SSLSocket;

/** TLS-terminating peek proxy: accepts TLS (device-local, fed by the iptables
 *  443 REDIRECT), terminates with our CA-signed cert, peeks the first bytes:
 *  HTTP/2 preface ('PRI ') -> gRPC (base+2); HTTP request ('GET '/'HEAD ') ->
 *  HTTP file server (base); anything else -> HTTP (best effort).
 *  base is per-package, see Net. */
public class TlsProxy {
    SSLContext sslContext;
    int listenPort;
    int base;
    volatile boolean run = true;
    SSLServerSocket ss;

    public TlsProxy(int listenPort, int base) throws Exception {
        this.listenPort = listenPort;
        this.base = base;
        KeyStore ks = KeyStore.getInstance("PKCS12");
        InputStream in = ProtobufCore.assetStream("server.p12");
        ks.load(in, "stub123".toCharArray());
        in.close();
        // find the PrivateKey entry and ensure the chain includes the CA
        String keyAlias = null;
        java.util.Enumeration<String> en = ks.aliases();
        while (en.hasMoreElements()) { String a = en.nextElement(); if (ks.isKeyEntry(a)) { keyAlias = a; break; } }
        java.security.Key pk = ks.getKey(keyAlias, "stub123".toCharArray());
        java.security.cert.Certificate[] ch = ks.getCertificateChain(keyAlias);
        if (ch != null && ch.length == 1) {
            java.security.cert.Certificate ca = null;
            java.util.Enumeration<String> en2 = ks.aliases();
            while (en2.hasMoreElements()) { String a2 = en2.nextElement(); if (!a2.equals(keyAlias) && ks.isCertificateEntry(a2)) { ca = ks.getCertificate(a2); break; } }
            if (ca == null) {
                try { java.security.cert.CertificateFactory cf = java.security.cert.CertificateFactory.getInstance("X.509");
                      ca = cf.generateCertificate(ProtobufCore.assetStream("lapis_ca.crt")); } catch (Throwable t) { L.log("ca asset: " + t); }
            }
            if (ca != null) {
                java.security.cert.Certificate[] ch2 = new java.security.cert.Certificate[]{ ch[0], ca };
                KeyStore ks2 = KeyStore.getInstance("PKCS12");
                ks2.load(null, null);
                ks2.setKeyEntry("server", pk, "stub123".toCharArray(), ch2);
                ks = ks2;
                L.log("tls chain rebuilt: leaf+CA");
            }
        }
        KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        kmf.init(ks, "stub123".toCharArray());
        sslContext = SSLContext.getInstance("TLS");
        sslContext.init(kmf.getKeyManagers(), null, null);
    }

    public void start() throws Exception {
        SSLServerSocketFactory f = sslContext.getServerSocketFactory();
        ss = (SSLServerSocket) f.createServerSocket(listenPort, 64, java.net.InetAddress.getByName("0.0.0.0"));
        L.log("tls proxy listening " + listenPort);
        Thread t = new Thread(() -> {
            while (run) {
                try {
                    SSLSocket s = (SSLSocket) ss.accept();
                    Thread h = new Thread(() -> pipe(s));
                    h.setDaemon(true);
                    h.start();
                } catch (Exception e) { if (run) break; }
            }
        });
        t.setDaemon(true);
        t.start();
    }

    int peekTarget(SSLSocket tls) throws Exception {
        try {
            javax.net.ssl.SSLParameters pp = tls.getSSLParameters();
            java.util.List<javax.net.ssl.SNIMatcher> ms =
                    new java.util.ArrayList<javax.net.ssl.SNIMatcher>();
            ms.add(new javax.net.ssl.SNIMatcher(0) {
                public boolean matches(javax.net.ssl.SNIServerName n) {
                    try { L.log("SNI: " + new String(n.getEncoded(), "UTF-8")); } catch (Throwable t2) {}
                    return true;
                }
            });
            pp.setSNIMatchers(ms);
            tls.setSSLParameters(pp);
        } catch (Throwable t) { L.log("sni hook: " + t); }
        tls.setSoTimeout(15000);
        java.io.PushbackInputStream pin = new java.io.PushbackInputStream(tls.getInputStream(), 32);
        byte[] head = new byte[9];
        int got = 0;
        while (got < 9) {
            int n = pin.read(head, got, 9 - got);
            if (n <= 0) break;
            got += n;
        }
        pin.unread(head, 0, got);
        String s = new String(head, 0, got > 4 ? 4 : got, "UTF-8");
        if (s.startsWith("PRI ")) return base + 2;         // gRPC h2 preface
        if (s.startsWith("GET ") || s.startsWith("HEAD ") || s.startsWith("POST ")) return base;
        return base;                                      // default: HTTP server
    }

    void pipe(SSLSocket tls) {
        Socket target = null;
        try {
            int port = peekTarget(tls);
            L.log("tls -> 127.0.0.1:" + port);
            tls.setSoTimeout(60000);
            target = new Socket();
            target.connect(new InetSocketAddress("127.0.0.1", port), 5000);
            InputStream in = tls.getInputStream();
            OutputStream out = tls.getOutputStream();
            InputStream tin = target.getInputStream();
            OutputStream tout = target.getOutputStream();
            Thread a = new Thread(() -> copy(in, tout));
            Thread b = new Thread(() -> copy(tin, out));
            a.setDaemon(true); b.setDaemon(true);
            a.start(); b.start();
            a.join(300000); b.join(300000);
        } catch (Exception e) {
            L.log("tls pipe: " + e);
        } finally {
            try { tls.close(); } catch (Exception ignored) {}
            try { if (target != null) target.close(); } catch (Exception ignored) {}
        }
    }

    void copy(InputStream in, OutputStream out) {
        try {
            byte[] b = new byte[16384]; int n;
            while ((n = in.read(b)) > 0) out.write(b, 0, n);
            out.flush();
        } catch (Exception ignored) {}
    }

    public void stop() throws Exception { run = false; if (ss != null) ss.close(); }
}

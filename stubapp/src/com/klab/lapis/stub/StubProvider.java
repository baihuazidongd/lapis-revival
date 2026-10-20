package com.klab.lapis.stub;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import java.io.File;

/** Auto-initializes when the host process starts (before Application.onCreate).
 *  In the merged game APK this starts the local servers and writes the
 *  endpoint prefs as early as possible. No user interaction needed. */
public class StubProvider extends ContentProvider {
    static boolean started = false;

    @Override
    public boolean onCreate() {
        android.content.Context c = getContext();
        String pkg = c.getPackageName();
        L.log(c, "StubProvider init in " + pkg);
        // In the merged game APK write the endpoint prefs so the client connects to the in-process
        // servers from the very first boot. Unity derives this file's name from the application id
        // (<pkg>.v2.playerprefs), so it must be derived the same way here: hard-coding the CN name
        // left the JP build reading a file nobody wrote, and it sat on "version info failed" forever
        // while the CN build (where the two names happen to coincide) worked.
        if (ProtobufCore.isHostPackage(pkg)) {
            try {
                android.content.SharedPreferences p =
                        c.getSharedPreferences(pkg + ".v2.playerprefs", 0);
                p.edit().putString("endpoint_host", "127.0.0.1")
                        .putInt("endpoint_port", Net.grpc(pkg)).commit();
                L.log(c, "endpoint prefs written to " + pkg + ".v2.playerprefs");
            } catch (Throwable t) {
                L.log(c, "prefs write failed: " + t);
            }
            // The client deletes the master databases once its own install step finishes, which
            // would leave the next boot's Lua bootstrap reading an empty Config table; restoring
            // them before Unity starts is what the game itself would have done on a second launch.
            try {
                Seed.pass(c);
            } catch (Throwable t) { L.log(c, "seed failed: " + t); }
            Seed.schedule(c, 3_000, 45_000);
            // The resource tree is gigabytes, so it gets its own thread and a window long enough to
            // finish on slow storage. Doing it inside the pass() above would block bindApplication
            // and ANR the process mid-write.
            Seed.installTreeAsync(c);
            Seed.scheduleTree(c, 5_000, 20L * 60_000L);
        }
        if (!started) {
            started = true;
            new Thread(() -> {
                try {
                    ProtobufCore core = new ProtobufCore(c);
                    HttpFileServer http = new HttpFileServer(Net.http(pkg), core);
                    http.start();
                    GrpcApi api = new GrpcApi(core);
                    api.start(Net.grpc(pkg), null);
                    try {
                        TlsProxy tp = new TlsProxy(Net.tls(pkg), Net.base(pkg));
                        tp.start();
                        L.log(c, "tls proxy 443->" + Net.tls(pkg) + " up (provider)");
                    } catch (Throwable t) { L.log(c, "tls proxy failed: " + t); }
                    L.log(c, "servers up: grpc " + Net.grpc(pkg) + ", http " + Net.http(pkg));
                } catch (Throwable t) {
                    L.log(c, "server start failed: " + t);
                }
            }).start();
        }
        return true;
    }

    @Override public Cursor query(Uri u, String[] p, String s, String[] a, String o) { return null; }
    @Override public String getType(Uri u) { return null; }
    @Override public Uri insert(Uri u, ContentValues v) { return null; }
    @Override public int delete(Uri u, String s, String[] a) { return 0; }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { return 0; }
}

package com.klab.lapis.stub;

import android.app.Service;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.os.IBinder;
import android.os.Build;

public class StubService extends Service {
    static final String CH = "lapis_stub";
    GrpcApi grpcApi;
    HttpFileServer httpServer;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CH, "LapisStub", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CH) : new Notification.Builder(this);
        b.setSmallIcon(android.R.drawable.ic_menu_manage).setContentTitle("LapisStub")
                .setContentText("local servers running");
        startForeground(1, b.build());
        try {
            try {
                Class<?> c1 = Class.forName("com.google.common.util.concurrent.AbstractFuture$TrustedFuture");
                L.log(this, "guava check OK: " + c1);
                Class<?> c2 = Class.forName("io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder");
                L.log(this, "netty check OK: " + c2);
            } catch (Throwable t) {
                L.log(this, "CLASS CHECK FAILED: " + t);
            }
            ProtobufCore core = new ProtobufCore(this);
            String pkg = getPackageName();
            httpServer = new HttpFileServer(Net.http(pkg), core);
            httpServer.start();
            grpcApi = new GrpcApi(core);
            grpcApi.start(Net.grpc(pkg), Net.grpc2(pkg));
            try {
                TlsProxy tp = new TlsProxy(Net.tls(pkg), Net.base(pkg));
                tp.start();
                L.log("tls proxy 443->" + Net.tls(pkg) + " up");
            } catch (Throwable t) { L.log("tls proxy failed: " + t); }
            L.log(this, "servers up: grpc " + Net.grpc(pkg) + ", http " + Net.http(pkg));
        } catch (Exception e) {
            L.log(this, "start failed: " + e);
            e.printStackTrace();
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        try { if (grpcApi != null) grpcApi.stop(); } catch (Exception ignored) {}
        try { if (httpServer != null) httpServer.stop(); } catch (Exception ignored) {}
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}

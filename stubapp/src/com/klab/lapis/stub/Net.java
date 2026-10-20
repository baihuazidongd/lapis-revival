package com.klab.lapis.stub;

/** Per-package port base.
 *
 *  Both packages used to bind 18080/18082/18083/18084, so on a device with both installed the
 *  second one either failed to bind or, worse, was answered by the first one's stub and read the
 *  wrong save. The client learns the gRPC port from its own <pkg>.v2.playerprefs (written here)
 *  and the asset port from one baked string in assets/bin/Data, so both sides can move together.
 */
public final class Net {
    public static int base(String pkg) {
        return pkg != null && pkg.endsWith(".jp") ? 18090 : 18080;
    }
    public static int http(String pkg) { return base(pkg); }
    public static int grpc(String pkg) { return base(pkg) + 2; }
    public static int grpc2(String pkg) { return base(pkg) + 3; }
    public static int tls(String pkg) { return base(pkg) + 4; }
}

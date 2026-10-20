package com.klab.lapis.stub;

import java.io.InputStream;
import java.io.OutputStream;

import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.MethodDescriptor;
import io.grpc.ServerServiceDefinition;
import io.grpc.stub.StreamObserver;

public class GrpcApi {
    Server server;
    Server tlsServer;
    final ProtobufCore core;

    public GrpcApi(ProtobufCore core) { this.core = core; }

    static MethodDescriptor.Marshaller<byte[]> BYTES = new BytesMarshaller();

    static class BytesMarshaller implements MethodDescriptor.Marshaller<byte[]> {
        public byte[] parse(InputStream stream) {
            try { return readAll(stream); } catch (Exception e) { throw new RuntimeException(e); }
        }
        public InputStream stream(byte[] value) { return new java.io.ByteArrayInputStream(value); }
    }

    static byte[] readAll(InputStream in) throws Exception {
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192]; int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        return bos.toByteArray();
    }

    static MethodDescriptor<byte[], byte[]> method(String name, MethodDescriptor.MethodType type) {
        return MethodDescriptor.<byte[], byte[]>newBuilder()
                .setType(type)
                .setFullMethodName("game.Lapis/" + name)
                .setRequestMarshaller(BYTES)
                .setResponseMarshaller(BYTES)
                .build();
    }

    io.grpc.ServerInterceptor tracer = new io.grpc.ServerInterceptor() {
        public <ReqT, RespT> io.grpc.ServerCall.Listener<ReqT> interceptCall(
                io.grpc.ServerCall<ReqT, RespT> call, io.grpc.Metadata headers,
                io.grpc.ServerCallHandler<ReqT, RespT> next) {
            L.log("RPC " + call.getMethodDescriptor().getFullMethodName());
            return next.startCall(call, headers);
        }
    };

    ServerServiceDefinition.Builder serviceBuilder() {
        ServerServiceDefinition.Builder svc = ServerServiceDefinition.builder("game.Lapis");
        svc.addMethod(method("Call", MethodDescriptor.MethodType.UNARY),
                io.grpc.stub.ServerCalls.asyncUnaryCall(
                        (byte[] req, StreamObserver<byte[]> obs) -> {
                            try { obs.onNext(core.call(req)); obs.onCompleted(); }
                            catch (Throwable e) { L.log("Call failed: " + e); obs.onError(map(e)); }
                        }));
        svc.addMethod(method("BidiCall", MethodDescriptor.MethodType.BIDI_STREAMING),
                io.grpc.stub.ServerCalls.asyncBidiStreamingCall(
                        (StreamObserver<byte[]> obs) -> new StreamObserver<byte[]>() {
                            public void onNext(byte[] req) {
                                try { obs.onNext(core.call(req)); } catch (Throwable e) { obs.onError(map(e)); }
                            }
                            public void onError(Throwable t) { }
                            public void onCompleted() { obs.onCompleted(); }
                        }));
        svc.addMethod(method("GetVerManifest", MethodDescriptor.MethodType.UNARY),
                io.grpc.stub.ServerCalls.asyncUnaryCall(
                        (byte[] req, StreamObserver<byte[]> obs) -> {
                            try { L.log("GetVerManifest hit"); obs.onNext(core.getVerManifest(req)); obs.onCompleted(); }
                            catch (Throwable e) { L.log("GVM failed: " + e); obs.onError(map(e)); }
                        }));
        svc.addMethod(method("GetMaintenance", MethodDescriptor.MethodType.UNARY),
                io.grpc.stub.ServerCalls.asyncUnaryCall(
                        (byte[] req, StreamObserver<byte[]> obs) -> {
                            try { obs.onNext(core.getMaintenance(req)); obs.onCompleted(); }
                            catch (Throwable e) { obs.onError(map(e)); }
                        }));
        svc.addMethod(method("GetAssetUrls", MethodDescriptor.MethodType.UNARY),
                io.grpc.stub.ServerCalls.asyncUnaryCall(
                        (byte[] req, StreamObserver<byte[]> obs) -> {
                            try { obs.onNext(core.getAssetUrls(req)); obs.onCompleted(); }
                            catch (Throwable e) { obs.onError(map(e)); }
                        }));
        svc.addMethod(method("GetRefundUrl", MethodDescriptor.MethodType.UNARY),
                io.grpc.stub.ServerCalls.asyncUnaryCall(
                        (byte[] req, StreamObserver<byte[]> obs) -> {
                            try { obs.onNext(core.getRefundUrl(req)); obs.onCompleted(); }
                            catch (Throwable e) { obs.onError(map(e)); }
                        }));
        return svc;
    }

    public void start(int plaintextPort, Integer tlsPort) throws Exception {
        server = io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder
                .forAddress(new java.net.InetSocketAddress(java.net.InetAddress.getByAddress(new byte[]{0,0,0,0}), plaintextPort))
                .maxInboundMessageSize(262144)
                .intercept(tracer)
                .addService(serviceBuilder().build())
                .build()
                .start();
        L.log("grpc plaintext listening " + plaintextPort);
        if (tlsPort != null) {
            java.security.KeyStore kmStore = java.security.KeyStore.getInstance("PKCS12");
            InputStream p12 = ProtobufCore.assetStream("server.p12");
            kmStore.load(p12, "stub123".toCharArray());
            p12.close();
            javax.net.ssl.KeyManagerFactory kmf =
                    javax.net.ssl.KeyManagerFactory.getInstance(javax.net.ssl.KeyManagerFactory.getDefaultAlgorithm());
            kmf.init(kmStore, "stub123".toCharArray());
            io.grpc.netty.shaded.io.netty.handler.ssl.SslContextBuilder sb =
                    io.grpc.netty.shaded.io.netty.handler.ssl.SslContextBuilder.forServer(kmf);
            io.grpc.netty.shaded.io.grpc.netty.GrpcSslContexts.configure(sb);
            io.grpc.netty.shaded.io.netty.handler.ssl.SslContext sslCtx2 = sb.build();
            tlsServer = io.grpc.netty.shaded.io.grpc.netty.NettyServerBuilder
                    .forAddress(new java.net.InetSocketAddress(java.net.InetAddress.getByAddress(new byte[]{0,0,0,0}), tlsPort.intValue()))
                    .maxInboundMessageSize(262144)
                    .sslContext(sslCtx2)
                    .intercept(tracer)
                    .addService(serviceBuilder().build())
                    .build()
                    .start();
            L.log("grpc tls listening " + tlsPort);
        }
    }

    static Throwable map(Throwable e) { return io.grpc.Status.INTERNAL.withDescription("stub: " + e).asRuntimeException(); }

    public void stop() throws Exception {
        if (server != null) server.shutdownNow();
        if (tlsServer != null) tlsServer.shutdownNow();
    }
}

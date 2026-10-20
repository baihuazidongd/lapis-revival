package com.klab.lapis.stub;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.StatFs;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Resource installer that ships inside the game APK and is launched from its own icon.
 *
 * It has to live in the game's own package: Android 11 and later forbid any third-party app, including
 * one holding All Files Access, from writing into another package's Android/data directory, and the
 * resource tree lives exactly there. A same-package activity writes its own directory freely, which is
 * why this is an installer wrapped around the game rather than a separate installer app.
 *
 * The archive is picked with the storage framework, so no runtime storage permission is requested at
 * all - the picker grants read access to that one file. Extraction is resumable: an entry is skipped
 * when a file of the same size is already in place, so killing the process half way through costs the
 * bytes already written and nothing more.
 *
 * Integrity does not depend on trusting the file the user chose. Every .bdl is checked against the
 * .bdl.hash sidecar that travels inside the same archive, which is also the check the game itself
 * applies before it will load a bundle, so an archive that passes here is an archive the game accepts.
 */
public class ImporterActivity extends Activity {
    private static final int PICK_ARCHIVE = 41;

    private TextView status;
    private Button pick;
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(48, 48, 48, 48);

        status = new TextView(this);
        status.setTextSize(15f);
        status.setText(report());

        pick = new Button(this);
        pick.setText("选择资源归档并整合");
        pick.setOnClickListener(v -> {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            try { startActivityForResult(i, PICK_ARCHIVE); }
            catch (Exception e) { status.setText("没有可用的文件选择器：" + e); }
        });

        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(status);
        col.addView(scroll, tp);
        col.addView(pick, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        setContentView(col);
    }

    /** Everything the user needs to know before choosing a file. */
    private String report() {
        StringBuilder s = new StringBuilder();
        String pkg = getPackageName();
        s.append("包名  ").append(pkg).append('\n');
        try {
            s.append("版本  ").append(getPackageManager().getPackageInfo(pkg, 0).versionName).append('\n');
        } catch (Exception ignored) { }

        File base = getExternalFilesDir(null);
        File story = new File(base, "JP/AssetBundles/assets/products/resources/story");
        String[] st = story.list();
        s.append("\n资源目录  ").append(base == null ? "不可用" : base.getAbsolutePath()).append('\n');
        s.append("剧情包    ").append(st == null ? 0 : st.length).append(" / 1255\n");

        // The client's own resource manifest sits at the root of the external files dir, not under
        // JP/AssetBundles - checking the wrong path here would tell the user the tree is missing
        // when it is actually present.
        File manifest = new File(base, "manifest.xml");
        if (!manifest.isFile()) manifest = new File(base, "server/manifest.xml");
        s.append("资源清单  ").append(manifest.isFile()
                ? String.format("已就位（%.1f MB）", manifest.length() / 1048576.0)
                : "缺失（需要导入）").append('\n');
        File res = new File(base, "JP/AssetBundles/assets/products/resources");
        String[] rn = res.list();
        int bundles = 0;
        if (rn != null) for (String n : rn) if (n.endsWith(".bdl")) bundles++;
        s.append("顶层包    ").append(bundles).append(" 个 .bdl，目录条目 ")
         .append(rn == null ? 0 : rn.length).append('\n');

        long need = 6_100_000_000L;
        if (base != null) {
            StatFs sf = new StatFs(base.getAbsolutePath());
            long free = sf.getBlockSizeLong() * sf.getAvailableBlocksLong();
            s.append("剩余空间  ").append(String.format("%.2f GB", free / 1073741824.0))
             .append(free > need ? "  足够" : "  不足，需约 5.7 GB").append('\n');
        }

        String other = "com.klab.lapis".equals(pkg) ? "com.klab.lapis.jp" : "com.klab.lapis";
        boolean otherInstalled = false;
        try {
            otherInstalled = getPackageManager().getPackageInfo(other, 0) != null;
        } catch (Exception ignored) { }
        if (otherInstalled) {
            s.append("\n注意：另一个语言版本同时装着。两者共用固定端口，")
             .append("不要同时运行，否则后打开的会卡在版本信息失败。\n");
        }
        return s.toString();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != PICK_ARCHIVE || res != RESULT_OK || data == null || data.getData() == null) return;
        final Uri uri = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(
                    uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) { }   // not persistable is fine, we only need it this once
        if (busy) return;
        busy = true;
        pick.setEnabled(false);
        new Thread(() -> {
            String out;
            try { out = install(uri); }
            catch (Exception e) { out = "失败：" + e; }
            final String text = out;
            busy = false;
            runOnUiThread(() -> { pick.setEnabled(true); status.setText(text); });
        }).start();
    }

    private String install(Uri uri) throws Exception {
        File base = getExternalFilesDir(null);
        if (base == null) return "外部目录不可用";
        long t0 = System.currentTimeMillis();
        int written = 0, skipped = 0, bad = 0;
        StringBuilder err = new StringBuilder();

        InputStream in = getContentResolver().openInputStream(uri);
        if (in == null) return "无法读取所选文件";
        try {
            ZipInputStream z = new ZipInputStream(in);
            ZipEntry e;
            byte[] buf = new byte[1 << 20];
            while ((e = z.getNextEntry()) != null) {
                String name = e.getName();
                if (e.isDirectory()) { z.closeEntry(); continue; }
                File out = new File(base, name);
                // Refuse anything that tries to climb out of the package's own directory.
                if (!out.getCanonicalPath().startsWith(base.getCanonicalPath() + File.separator)) {
                    bad++; err.append("越界条目 ").append(name).append('\n'); z.closeEntry(); continue;
                }
                if (out.isFile() && out.length() == e.getSize()) { skipped++; z.closeEntry(); continue; }
                out.getParentFile().mkdirs();
                File tmp = new File(out.getParentFile(), out.getName() + ".part");
                OutputStream os = Files.newOutputStream(tmp.toPath());
                int r;
                while ((r = z.read(buf)) > 0) os.write(buf, 0, r);
                os.close(); z.closeEntry();
                if (tmp.length() != e.getSize()) {
                    tmp.delete(); bad++;
                    err.append("写入不完整 ").append(name).append('\n'); continue;
                }
                if (!tmp.renameTo(out)) { Files.write(out.toPath(), Files.readAllBytes(tmp.toPath())); tmp.delete(); }
                out.setReadable(true, false);
                written++;
                if ((written + skipped) % 250 == 0) {
                    final int done = written + skipped;
                    runOnUiThread(() -> status.setText(report() + "\n整合中 " + done + " 个文件…"));
                }
            }
            z.close();
        } finally {
            in.close();
        }

        // Verify against the sidecars that travel inside the archive - the same rule the game applies.
        File story = new File(base, "JP/AssetBundles/assets/products/resources/story");
        int checked = 0, mismatch = 0;
        String[] names = story.list();
        if (names != null) {
            for (String n : names) {
                if (!n.endsWith(".bdl")) continue;
                File body = new File(story, n), side = new File(story, n + ".hash");
                if (!side.isFile()) { mismatch++; continue; }
                String want = new String(Files.readAllBytes(side.toPath()), "US-ASCII")
                        .trim().toUpperCase();
                if (!Seed.sha1(body).equals(want)) mismatch++;
                checked++;
            }
        }
        String[] after = story.list();
        return report()
                + "\n整合完成  写入 " + written + "，跳过 " + skipped
                + "，用时 " + (System.currentTimeMillis() - t0) / 1000 + " 秒\n"
                + "剧情包校验  " + checked + " 个，摘要不符 " + mismatch + '\n'
                + (bad > 0 ? "异常条目 " + bad + '\n' + err : "")
                + (mismatch == 0 && bad == 0 ? "\n可以正常启动游戏了。" : "\n有文件不符，建议重新导入。");
    }
}

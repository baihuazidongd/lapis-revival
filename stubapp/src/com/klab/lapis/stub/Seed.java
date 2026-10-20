package com.klab.lapis.stub;

import android.content.Context;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;

/** Keeps the two master databases materialised at the paths the client's update
 *  pass writes them to. The client deletes them once its install step finishes,
 *  which leaves the next boot's Lua bootstrap reading an empty Config table, so
 *  restoring them from the packaged copy before Unity starts is what the game
 *  itself would have done on a second launch. */
class Seed {
    /** rel, assets path, and the SHA-1 of the bytes this build was verified against.
     *  The master db is the shipped table with a few edits: Config.ShopFirstLook {1,1} to {2,1}, so
     *  the entry points that take their landing tab from that config open the item shop (real,
     *  buyable goods) instead of the recharge tab (a payment-SDK storefront); every CardPool row
     *  widened to OpenTime 2019-08-05 / EndTime 2099-12-31 with ActiveType and CreateAccountPoolTime
     *  cleared and m_block_cardpool emptied, which is what puts all 114 banners on the summon page
     *  (open_all.py); and the shop-tab landing experiments. Keep this comment ASCII: SeedHashTest
     *  compiles Seed.java without -encoding UTF-8, and any CJK here fails the build. */
    static final String[][] TARGETS = {
            { "MasterData/master_data.db", "res/MasterData/master_data.db",
              "B9E73077BBDD0C741650FABABE4B78061DF24AF8" },
            { "JP/master_data_lang.db", "res/JP/master_data_lang.db",
              "3BB8F350AA72ECEC8CA545D0F85D48045F3CE433" },
            // Exactly one file in the 5,305-bundle tree is broken, and it is enough to brick the
            // client: activityassets/pickupray4/bg.bdl arrived from the CDN as ZERO bytes (its own
            // .bdl.hash sidecar is da39a3ee..., the SHA-1 of nothing), so Unity answers "Unable to
            // read header from archive file", the AssetBundle load returns null, a
            // NullReferenceException follows and the Loading overlay never hides. The shipped game
            // never noticed because the three banners that depend on it have been off-sale since
            // 2022; opening every pool makes them load, which is how this surfaced. The real 679,926
            // byte archive is packaged and healed like the databases. "bdl" says to also write the
            // .bdl.hash sidecar, which is how the client gates a bundle load.
            { "JP/AssetBundles/assets/products/resources/activityassets/pickupray4/bg.bdl",
              "res/JP/pickupray4_bg.bdl",
              "7CAFDF4A7BD60886394E0154BA3679D873A7BA16", "bdl" },
    };

    /** The whole story directory as ONE stored zip, so a fresh install needs no resource push.
     *  Pinned by the archive digest rather than per file: the zip was built from the running device
     *  tree and every one of its 1254 files was compared byte for byte against that tree first, so a
     *  single digest gates a set that would otherwise need 1254 constants. Four official sidecars end
     *  in a newline and are shipped untouched - the loader accepts them today, "normalising" them
     *  would be an unrequested change to bytes that provably work.
     *  Keep ASCII: SeedHashTest compiles this file without -encoding UTF-8. */
    static final String STORY_REL   = "JP/AssetBundles/assets/products/resources/story";
    static final String STORY_ASSET = "res/JP/story.zip";
    static final String STORY_SHA1  = "5FF152CBC530906471CF2C555A0FB523E2A915A7";
    /** Files in this build's archive, flipped with it by pkg_story.py. The two packages do NOT
     *  agree: the CN tree carries 627 bundles and 627 sidecars, the pristine JP tree is missing
     *  huawieyinv0203_scene.bdl.hash, so it holds 1253. A hard-coded 1254 would make the JP build
     *  judge its own archive permanently incomplete and retry the extraction until the window
     *  closes without ever settling. */
    static final int STORY_MIN      = 1254;
    static volatile boolean storySettled = false;

    /** The ENTIRE resource tree, so sharing the game is one file instead of an APK plus a 5.7 GB
     *  push. Pinned by archive digest like the story set; the archive is built from the running,
     *  verified device tree rather than from any host-side staging copy.
     *  Extraction runs on its own thread, NOT inside the synchronous pass() at StubProvider.onCreate:
     *  five and a half gigabytes on the main thread during bindApplication is an ANR, and Android
     *  killing the process half way through is exactly the state this code must survive. It survives
     *  because every file is skipped when it is already present at the right size, so a relaunch
     *  resumes instead of restarting. */
    static final String TREE_REL   = "";
    static final String TREE_ASSET = "res/JP/tree.zip";
    static final String TREE_SHA1  = "0000000000000000000000000000000000000000";
    static final int TREE_MIN      = 1;
    static volatile boolean treeRunning = false;
    static volatile boolean treeSettled = false;

    static void schedule(final Context c, final long delayMs, final long ms) {
        Thread t = new Thread(() -> {
            try { Thread.sleep(delayMs); } catch (InterruptedException ignored) {}
            long end = System.currentTimeMillis() + ms;
            while (System.currentTimeMillis() < end) {
                try { pass(c); } catch (Throwable e) { L.log(c, "SEED fatal: " + e); return; }
                try { Thread.sleep(150); } catch (InterruptedException e) { return; }
            }
            L.log(c, "SEED done");
        });
        t.setDaemon(true);
        t.start();
    }

    /** Install the packaged resource tree on a background thread. Returns immediately. */
    static void installTreeAsync(final Context c) {
        if (treeRunning || treeSettled) return;
        treeRunning = true;
        Thread t = new Thread(() -> {
            try { tree(c); } catch (Throwable e) { L.log(c, "SEED tree fatal: " + e); }
            treeRunning = false;
        });
        t.setDaemon(true);
        t.start();
    }

    /**
     * A user-dropped archive wins over the packaged one. Sharing the game then means handing someone
     * an APK plus one file they copy into the package's own directory - no picker, no runtime
     * permission, no root. Consumed on success so a later boot does not re-import it.
     */
    static File pendingArchive(Context c) {
        File base = c.getExternalFilesDir(null);
        if (base == null) return null;
        File f = new File(base, "import.zip");
        return f.isFile() && f.length() > 0 ? f : null;
    }

    static void tree(Context c) throws Exception {
        if (treeSettled) return;
        File base = c.getExternalFilesDir(null);
        if (base == null) return;
        File dst = new File(base, TREE_REL);
        File dropped = pendingArchive(c);
        // The "tree already there, nothing to do" shortcut must not fire while an archive is waiting:
        // in a build that does not package the tree TREE_MIN is 1, so the directory always looks
        // "complete" and a user-dropped import would be silently skipped forever.
        if (dropped == null) {
            String[] have = dst.list();
            if (have != null && have.length >= TREE_MIN) { treeSettled = true; return; }
        }
        File zip = dropped != null ? dropped : source(c, TREE_ASSET);
        if (dropped != null) L.log(c, "SEED tree using dropped archive " + zip.length() + "B");
        if (zip == null) { treeSettled = true; L.log(c, "SEED tree no source"); return; }
        // Only the packaged archive is gated by its digest. A user-dropped one is never compared,
        // and hashing it first would read all 5.6 GB twice on every install.
        if (dropped == null) {
            String got = sha1(zip);
            if (!got.equals(TREE_SHA1)) {
                zip.delete(); treeSettled = true;
                L.log(c, "SEED tree refused sha1=" + got + " expected=" + TREE_SHA1);
                return;
            }
        }
        long t0 = System.currentTimeMillis();
        int written = 0, skipped = 0;
        boolean bailed = false;
        boolean drained = false;
        try {
            java.util.zip.ZipInputStream zin =
                    new java.util.zip.ZipInputStream(Files.newInputStream(zip.toPath()));
            java.util.zip.ZipEntry e;
            byte[] buf = new byte[1 << 20];
            while ((e = zin.getNextEntry()) != null) {
                String name = e.getName();
                File out = new File(dst, name);
                if (e.isDirectory()) { out.mkdirs(); zin.closeEntry(); continue; }
                // Resume rule: same name and same size is the same bytes. The archive is stored, not
                // deflated, so the central directory carries an exact uncompressed size for every
                // entry and a truncated write from a killed run cannot pass this test.
                if (out.isFile() && out.length() == e.getSize()) { skipped++; zin.closeEntry(); continue; }
                File parent = out.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) {
                    L.log(c, "SEED tree mkdir failed " + parent.getAbsolutePath());
                    bailed = true;
                    break;
                }
                File tmp = new File(parent, out.getName() + ".seedpart");
                OutputStream os = Files.newOutputStream(tmp.toPath());
                int r;
                while ((r = zin.read(buf)) > 0) os.write(buf, 0, r);
                os.close(); zin.closeEntry();
                if (tmp.length() != e.getSize()) {
                    tmp.delete();
                    L.log(c, "SEED tree short write " + name + " " + tmp.length() + "!=" + e.getSize());
                    bailed = true;
                    break;
                }
                if (!tmp.renameTo(out)) { copy(tmp, out); tmp.delete(); }
                out.setReadable(true, false);
                written++;
                if ((written % 400) == 0) {
                    long done = written + skipped;
                    L.log(c, "SEED tree progress " + done + "/" + TREE_MIN
                            + " (" + (System.currentTimeMillis() - t0) / 1000 + "s)");
                }
            }
            zin.close();
            drained = !bailed;
        } finally {
            // Only discard the archive once every entry has been read. Deleting it after an
            // interrupted run would eat the user's one copy while the skip-by-size resume rule
            // still needs it to finish the tree.
            if (drained) zip.delete();
        }
        if (drained) {
            treeSettled = true;
            if (dropped != null) dropped.delete();
            // A fresh install drops a forceupdate marker and then demands the whole CDN set -
            // several gigabytes the client cannot get offline. Having just materialised that set
            // from the packaged or dropped archive, the marker is no longer true and leaving it
            // makes the client block on a "will download 4221 MB" prompt instead of playing.
            File force = new File(base, "forceupdate");
            if (force.isFile() && force.delete()) L.log(c, "SEED cleared forceupdate");
            L.log(c, "SEED tree installed wrote=" + written + " skipped=" + skipped
                    + " in " + (System.currentTimeMillis() - t0) / 1000 + "s");
        } else {
            String[] now = dst.list();
            L.log(c, "SEED tree incomplete entries=" + (now == null ? 0 : now.length)
                    + " wrote=" + written + " skipped=" + skipped + ", archive kept for resume");
        }
    }

    /** Retry window for the tree installer. Extraction resumes from wherever a killed run stopped,
     *  so this can run for minutes without duplicating work.
     *
     *  The second phase is the point of this function. The loop used to stop the instant
     *  treeSettled turned true, so a user who dropped import.zip in after the packaged tree had
     *  already installed had nothing looking at their file - the drop only became visible by killing
     *  the process, which is the "one manual relaunch" the README had to document. Once the install
     *  window closes this keeps watching, one stat() per ten seconds, and re-arms the importer when
     *  an archive shows up. It is a daemon thread, so it costs nothing once the process ends.
     */
    static void scheduleTree(final Context c, final long delayMs, final long ms) {
        Thread t = new Thread(() -> {
            if (!nap(delayMs)) return;
            long end = System.currentTimeMillis() + ms;
            while (System.currentTimeMillis() < end) {
                if (pendingArchive(c) != null) treeSettled = false;
                if (!treeRunning && !treeSettled) {
                    try { tree(c); } catch (Throwable e) { L.log(c, "SEED tree fatal: " + e); return; }
                }
                if (!nap(2000)) return;
            }
            while (true) {
                if (pendingArchive(c) != null) {
                    L.log(c, "SEED dropped archive arrived after settle, importing without a restart");
                    treeSettled = false;
                    if (!treeRunning) {
                        try { tree(c); } catch (Throwable e) { L.log(c, "SEED tree fatal: " + e); return; }
                    }
                }
                if (!nap(10_000)) return;
            }
        });
        t.setDaemon(true);
        t.start();
    }

    /** Sleep that reports interruption, so a killed process ends the watcher instead of spinning. */
    static boolean nap(long ms) {
        try { Thread.sleep(ms); return true; } catch (InterruptedException e) { return false; }
    }

    static void pass(Context c) throws Exception {
        File base = c.getExternalFilesDir(null);
        if (base == null) return;
        for (String[] t : TARGETS) {
            // Per target, and never fatal: this directory tree is written by three different
            // mechanisms (the client's own downloader, an adb push, the in-app importer) and a folder
            // left owned by `shell` at mode 755 is readable by the app but not writable by it, so one
            // target CAN fail while the rest are fine. Letting that throw out of pass() also skipped
            // story() and stopped every later retry, which turned one unwritable bundle into an
            // empty Config table.
            try {
                restore(c, base, t);
            } catch (Throwable e) {
                L.log(c, "SEED " + t[0] + " failed: " + e);
            }
        }
        story(c, base);
    }

    /** Install one TARGETS entry if the file is absent or empty. */
    static void restore(Context c, File base, String[] t) throws Exception {
        String rel = t[0];
        File dst = new File(base, rel);
        if (dst.isFile() && dst.length() > 0) return;
        File src = source(c, t[1]);
        if (src == null) { L.log(c, "SEED no source for " + rel); return; }
        // A half-read asset would otherwise be installed and then hashed from its own
        // truncated bytes, so the sidecar gate would certify a broken database.
        String got = sha1(src);
        if (!got.equals(t[2])) {
            src.delete();
            L.log(c, "SEED refused " + rel + " sha1=" + got + " expected=" + t[2]);
            return;
        }
        dst.getParentFile().mkdirs();
        File tmp = new File(dst.getParentFile(), dst.getName() + ".seed");
        copy(src, tmp);
        if (!tmp.renameTo(dst)) {
            copy(src, dst);
            tmp.delete();
        }
        src.delete();
        dst.setReadable(true, false);
        // The master db load is SHA-1 sidecar gated (40 uppercase hex, no newline) and the
        // language db is not, so only the first target needs its hash re-derived.
        if (rel.equals("MasterData/master_data.db")) writeHash(dst);
        // A bundle IS gated: the loader compares the sibling .bdl.hash before it will open the
        // archive, and every other sidecar in the tree is 40 hex plus a newline. Match that.
        if (t.length > 3 && "bdl".equals(t[3])) {
            OutputStream os = new java.io.FileOutputStream(dst.getAbsolutePath() + ".hash");
            os.write((got + "\n").getBytes("US-ASCII"));
            os.close();
            new File(dst.getParentFile(), dst.getName() + ".hash").setReadable(true, false);
        }
        L.log(c, "SEED restored " + t[0] + " " + dst.length() + "B");
    }

    /** Repair or install the packaged story tree. Checked once per process: listing 1255 entries on
     *  every 150 ms pass would cost more than the extraction it guards. */
    static void story(Context c, File base) throws Exception {
        if (storySettled) return;
        File dst = new File(base, STORY_REL);
        String[] have = dst.list();
        if (have != null && have.length >= STORY_MIN + 1) { storySettled = true; return; }
        File zip = source(c, STORY_ASSET);
        if (zip == null) { storySettled = true; L.log(c, "SEED story no source"); return; }
        String got = sha1(zip);
        if (!got.equals(STORY_SHA1)) {
            zip.delete(); storySettled = true;
            L.log(c, "SEED story refused sha1=" + got + " expected=" + STORY_SHA1);
            return;
        }
        // The archive carries no entry for the tree root itself, and mkdirs() reports failure by
        // returning false rather than throwing, so the first write died with NoSuchFileException and
        // every retry did the same. Create the root explicitly and say so if it will not take.
        if (!dst.isDirectory() && !dst.mkdirs()) {
            zip.delete();
            L.log(c, "SEED story cannot create " + dst.getAbsolutePath());
            return;
        }
        int n = 0;
        try {
            java.util.zip.ZipInputStream zin =
                    new java.util.zip.ZipInputStream(Files.newInputStream(zip.toPath()));
            java.util.zip.ZipEntry e;
            byte[] buf = new byte[1 << 16];
            while ((e = zin.getNextEntry()) != null) {
                String name = e.getName();
                if (!name.startsWith("story/")) { zin.closeEntry(); continue; }
                File out = new File(dst, name.substring(6));
                if (e.isDirectory()) { out.mkdirs(); zin.closeEntry(); continue; }
                if (!out.getParentFile().isDirectory() && !out.getParentFile().mkdirs()) {
                    L.log(c, "SEED story mkdir failed " + out.getAbsolutePath()); break;
                }
                OutputStream os = Files.newOutputStream(out.toPath());
                int r;
                while ((r = zin.read(buf)) > 0) os.write(buf, 0, r);
                os.close(); zin.closeEntry();
                out.setReadable(true, false);
                n++;
            }
            zin.close();
        } catch (Throwable err) {
            L.log(c, "SEED story failed at " + n + ": " + err);
        }
        zip.delete();
        // Only settle on a complete tree; an incomplete one is retried by the next pass until the
        // seeding window closes, so a half-written install cannot silently certify itself.
        if (n >= STORY_MIN) { storySettled = true; L.log(c, "SEED story installed " + n + " files"); }
    }

    static String sha1(File f) throws Exception {
        java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-1");
        byte[] buf = new byte[1 << 16];
        java.io.InputStream in = Files.newInputStream(f.toPath());
        for (int n; (n = in.read(buf)) > 0; ) md.update(buf, 0, n);
        in.close();
        StringBuilder sb = new StringBuilder();
        for (byte x : md.digest()) sb.append(String.format("%02X", x));
        return sb.toString();
    }

    static void writeHash(File db) throws Exception {
        Files.write(new File(db.getParentFile(), db.getName() + ".hash").toPath(),
                sha1(db).getBytes("US-ASCII"));
    }

    /** the database packaged in this APK's assets, unpacked to cache */
    static File source(Context c, String assetPath) {
        try {
            InputStream in = c.getAssets().open(assetPath);
            File tmp = new File(c.getCacheDir(), assetPath.replace('/', '_'));
            OutputStream os = Files.newOutputStream(tmp.toPath());
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            in.close();
            os.close();
            return tmp;
        } catch (Throwable e) { return null; }
    }

    static void copy(File from, File to) throws Exception {
        InputStream in = Files.newInputStream(from.toPath());
        OutputStream out = Files.newOutputStream(to.toPath());
        byte[] buf = new byte[1 << 16];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        out.close();
    }
}

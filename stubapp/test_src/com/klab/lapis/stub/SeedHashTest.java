package com.klab.lapis.stub;

import java.io.File;
import java.nio.file.Files;

/** Runs on the host: proves the two things Seed does to the packaged databases before any of it
 *  reaches a device -- that the pinned SHA-1 in TARGETS is the hash of the bytes actually staged,
 *  and that the sidecar it writes has the shape the client's gate demands (40 uppercase hex, no
 *  trailing newline). Also runs a one-byte mutation so a hash that never discriminates cannot pass. */
public class SeedHashTest {
    static int fails = 0;

    static void check(String what, boolean ok, String detail) {
        System.out.println((ok ? "PASS " : "FAIL ") + what + (detail.isEmpty() ? "" : " :: " + detail));
        if (!ok) fails++;
    }

    public static void main(String[] args) throws Exception {
        for (String[] t : Seed.TARGETS) {
            File db = new File(args[0], t[1]);
            if (!db.isFile()) { check("staged " + t[1], false, "missing"); continue; }

            String got = Seed.sha1(db);
            check("pin matches staged bytes " + t[0], t[2].equals(got), "pin=" + t[2] + " sha1=" + got);

            // independent implementation: compare against the shell's sha1sum for the same file
            Process p = new ProcessBuilder("sha1sum", db.getAbsolutePath())
                    .redirectErrorStream(true).start();
            String line = new String(p.getInputStream().readAllBytes(), "US-ASCII");
            p.waitFor();
            if (line.trim().isEmpty()) check("sha1sum available", false, "no output");
            else {
                // MSYS escapes the drive colon, so the digest field arrives as "\35e02.."; take the
                // hex by shape rather than by field index.
                java.util.regex.Matcher m = java.util.regex.Pattern.compile("[0-9a-fA-F]{40}").matcher(line);
                check("two implementations agree " + t[0],
                        m.find() && m.group().equalsIgnoreCase(got), "sha1sum=" + line.trim());
            }

            File dir = new File(System.getProperty("java.io.tmpdir"), "seedhashtest");
            dir.mkdirs();
            File copy = new File(dir, db.getName());
            Files.copy(db.toPath(), copy.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            Seed.writeHash(copy);
            File side = new File(dir, db.getName() + ".hash");
            byte[] raw = Files.readAllBytes(side.toPath());
            String text = new String(raw, "US-ASCII");
            check("sidecar is 40 bytes, no newline " + t[0], raw.length == 40, "len=" + raw.length);
            check("sidecar is uppercase hex " + t[0], text.matches("[0-9A-F]{40}"), text);
            check("sidecar names the db it gates " + t[0], text.equals(got), text);

            // mutation control: one flipped byte must move the digest, or none of the above means anything
            byte[] body = Files.readAllBytes(copy.toPath());
            body[body.length / 2] ^= 0x01;
            Files.write(copy.toPath(), body);
            String mutated = Seed.sha1(copy);
            check("digest discriminates a 1-byte change " + t[0], !mutated.equals(got), "mut=" + mutated);
            copy.delete();
            side.delete();
        }
        System.out.println(fails == 0 ? "ALL PASS" : fails + " FAIL");
        System.exit(fails == 0 ? 0 : 1);
    }
}

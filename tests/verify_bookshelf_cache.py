#!/usr/bin/env python3
"""Exercise the actual cover loader, including cache hits and failure recovery.

An optional second argument retains a benchmark binary. Run it with
`original|cached image...` to compare the same sources without network/UI work.
"""
from pathlib import Path
import os
import re
import shlex
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
function = re.search(r'static GdkPixbuf \*get_cover \(const char \*filename\)\n\{.*?\n\}', source, re.S).group()
program = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <utime.h>
#include <glib.h>
#include <glib/gstdio.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#define COVER_SIZE 128
#define PACKAGE_DATA_DIR "."
static const char *watched;
static int source_reads;
static GdkPixbuf *load(const char *name, GError **error) {
    if (watched && !strcmp(name, watched)) source_reads++;
    return gdk_pixbuf_new_from_file(name, error);
}
#define gdk_pixbuf_new_from_file load
''' + function + r'''
#undef gdk_pixbuf_new_from_file

/* Unmodified upstream scaling, used to compare pixels and benchmark. */
static GdkPixbuf *original(const char *filename) {
    GdkPixbuf *pb, *spb;
    int w, h;
    pb = gdk_pixbuf_new_from_file(filename, NULL);
    if (!pb) pb = gdk_pixbuf_new_from_file(PACKAGE_DATA_DIR "/nocover.png", NULL);
    h = gdk_pixbuf_get_height(pb);
    if (h == COVER_SIZE) return pb;
    w = gdk_pixbuf_get_width(pb);
    spb = gdk_pixbuf_scale_simple(pb, ((w > h) ? COVER_SIZE : COVER_SIZE * w / h),
        ((w > h) ? COVER_SIZE * h / w : COVER_SIZE), GDK_INTERP_BILINEAR);
    g_object_unref(pb);
    return spb;
}
static void fixture(const char *name, int w, int h, gboolean alpha) {
    GdkPixbuf *pb = gdk_pixbuf_new(GDK_COLORSPACE_RGB, alpha, 8, w, h);
    int channels = gdk_pixbuf_get_n_channels(pb);
    for (int y = 0; y < h; y++) {
        guchar *row = gdk_pixbuf_get_pixels(pb) + y * gdk_pixbuf_get_rowstride(pb);
        for (int x = 0; x < w; x++) {
            row[x * channels] = x % 256;
            row[x * channels + 1] = y % 256;
            row[x * channels + 2] = (x + y) % 256;
            if (alpha) row[x * channels + 3] = (x * y) % 256;
        }
    }
    GError *error = NULL;
    if (!gdk_pixbuf_save(pb, name, "png", &error, NULL))
        g_error("Cannot write %s: %s", name, error->message);
    g_object_unref(pb);
}
static void equal(GdkPixbuf *a, GdkPixbuf *b) {
    assert(a && b);
    assert(gdk_pixbuf_get_width(a) == gdk_pixbuf_get_width(b));
    assert(gdk_pixbuf_get_height(a) == gdk_pixbuf_get_height(b));
    assert(gdk_pixbuf_get_n_channels(a) == gdk_pixbuf_get_n_channels(b));
    for (int y = 0; y < gdk_pixbuf_get_height(a); y++)
        assert(!memcmp(gdk_pixbuf_get_pixels(a) + y * gdk_pixbuf_get_rowstride(a),
            gdk_pixbuf_get_pixels(b) + y * gdk_pixbuf_get_rowstride(b),
            gdk_pixbuf_get_width(a) * gdk_pixbuf_get_n_channels(a)));
}
static GdkPixbuf *check(const char *file, int reads) {
    GdkPixbuf *reference = original(file), *result;
    watched = file;
    source_reads = 0;
    result = get_cover(file);
    assert(source_reads == reads);
    equal(reference, result);
    watched = NULL;
    g_object_unref(reference);
    return result;
}
int main(int argc, char **argv) {
    if (argc > 1) {
        gint64 start = g_get_monotonic_time();
        for (int i = 2; i < argc; i++) {
            GdkPixbuf *pb = !strcmp(argv[1], "original") ? original(argv[i]) : get_cover(argv[i]);
            assert(pb);
            g_object_unref(pb);
        }
        printf("%s: %d covers, %.3f s\n", argv[1], argc - 2,
            (g_get_monotonic_time() - start) / 1000000.0);
        return 0;
    }
    char *cwd = g_get_current_dir();
    char *directory = g_build_filename(cwd, "cache", "bookshelf", "thumbnails", NULL);
    char *key = g_compute_checksum_for_string(G_CHECKSUM_SHA256, "portrait.png", -1);
    char *cache = g_strdup_printf("%s/%s.png", directory, key);
    char *cache_root = g_build_filename(cwd, "cache", NULL);
    g_setenv("XDG_CACHE_HOME", cache_root, TRUE);
    fixture("nocover.png", 80, 128, FALSE);
    fixture("portrait.png", 350, 600, FALSE);
    fixture("landscape.png", 600, 350, TRUE);
    fixture("sized.png", 92, 128, TRUE);
    const char *files[] = { "portrait.png", "landscape.png", "sized.png" };
    for (unsigned i = 0; i < G_N_ELEMENTS(files); i++) {
        GdkPixbuf *pb = check(files[i], 1);
        gdk_pixbuf_fill(pb, 0xff0000ff); /* caller's overlays must not enter cache */
        g_object_unref(pb);
        g_object_unref(check(files[i], 0));
    }
    GStatBuf before, after;
    assert(g_stat(cache, &before) == 0);
    g_object_unref(check("portrait.png", 0));
    assert(g_stat(cache, &after) == 0 && before.st_ino == after.st_ino);
    assert(g_file_set_contents(cache, "broken", -1, NULL));
    g_object_unref(check("portrait.png", 1));
    g_object_unref(check("portrait.png", 0));
    fixture(cache, 80, 128, FALSE); /* valid PNG, but missing source metadata */
    g_object_unref(check("portrait.png", 1));
    assert(g_stat("portrait.png", &before) == 0);
    struct utimbuf times = { before.st_atime, before.st_mtime + 10 };
    assert(g_utime("portrait.png", &times) == 0);
    g_object_unref(check("portrait.png", 1));
    fixture("portrait.png", 300, 610, FALSE); /* size changes, mtime unchanged */
    assert(g_utime("portrait.png", &times) == 0);
    g_object_unref(check("portrait.png", 1));
    assert(g_unlink(cache) == 0);
    assert(g_mkdir(cache, 0700) == 0); /* cache entry cannot be written */
    g_object_unref(check("portrait.png", 1));
    assert(g_rmdir(cache) == 0);
    char *saved = g_strconcat(directory, "-saved", NULL);
    assert(g_rename(directory, saved) == 0);
    assert(g_file_set_contents(directory, "blocked", -1, NULL));
    g_object_unref(check("portrait.png", 1)); /* cache directory unavailable */
    assert(g_unlink(directory) == 0);
    assert(g_rename(saved, directory) == 0);
    assert(g_file_set_contents("portrait.png", "broken", -1, NULL));
    g_object_unref(check("portrait.png", 1));
    assert(!g_file_test(cache, G_FILE_TEST_EXISTS)); /* do not cache fallback */
    assert(g_unlink("portrait.png") == 0);
    g_object_unref(check("portrait.png", 1));
    assert(!g_file_test(cache, G_FILE_TEST_EXISTS));
    puts("Bookshelf cache: pixel parity, cache hits, overlays, invalidation and failure recovery passed");
    g_free(saved); g_free(cache_root); g_free(cache); g_free(key); g_free(directory); g_free(cwd);
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'probe.c').write_text(program)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gdk-pixbuf-2.0'], text=True))
    binary = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else path / 'probe'
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(path / 'probe.c'), '-o', str(binary), *flags], check=True)
    # Only our generated fixtures are decoded here. Containers may forbid the
    # nested user namespaces required by glycin; leave application policy alone.
    env = dict(os.environ, GLYCIN_DISABLE_SANDBOX="i-know-the-risks")
    subprocess.run([str(binary)], cwd=path, env=env, check=True)

#!/usr/bin/env python3
"""Exercise Bookshelf's actual cover callbacks with a fake clock and catalogue."""
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
functions = []
for name in ('load_cover_for_item', 'find_cover_for_item', 'image_download_done'):
    functions.append(re.search(r'static (?:gboolean|void) ' + name + r' \([^\n]*\)\n\{.*?\n\}', source, re.S).group())
defines = '\n'.join(re.findall(r'^#define COVER_BATCH_.*$', source, re.M))
program = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <glib.h>
#define GTK_TREE_MODEL(model) (model)
#define ITEM_COVPATH 0
#define ITEM_DOWNLOADED 1
#define CACHE_PATH "/cache/"
#define F_OK 0
typedef enum { SUCCESS, FAILURE } tf_status;
static gboolean find_cover_for_item(gpointer data);
static void image_download_done(tf_status success);
static gboolean cover_dl, pdf_dl_req;
static int items, covitem, count, ready[200], seen[200], overlays[200];
static int downloads, pending, refreshes;
static gint64 clock_us, item_us;
static gboolean (*idle)(gpointer);
static void (*finished)(tf_status);
static gint64 fake_time(void) { return clock_us; }
#define g_get_monotonic_time fake_time
static void gtk_tree_model_get(int model, int *iter, ...) {
    va_list ap;
    va_start(ap, iter);
    assert(model == items && *iter >= 0 && *iter < count);
    assert(va_arg(ap, int) == ITEM_COVPATH);
    *va_arg(ap, char **) = g_strdup_printf("%d", *iter);
    assert(va_arg(ap, int) == ITEM_DOWNLOADED);
    *va_arg(ap, int *) = 0;
    assert(va_arg(ap, int) == -1);
    va_end(ap);
}
static char *get_local_path(char *path, const char *dir) {
    assert(!strcmp(dir, CACHE_PATH));
    return g_strdup(path);
}
static int access(const char *path, int mode) {
    assert(atoi(path) == covitem && mode == F_OK);
    return ready[covitem] ? 0 : -1;
}
static void update_cover_entry(char *path, int dl, gboolean new) {
    assert(atoi(path) == covitem && dl == 0);
    assert(!seen[covitem]);
    seen[covitem]++;
    overlays[covitem] = new;
    clock_us += item_us;
}
static gboolean gtk_tree_model_iter_next(int model, int *iter) {
    assert(model == items);
    return ++*iter < count;
}
static void refresh_icons(void) { refreshes++; }
static void get_pending_pdf(void) { pending++; pdf_dl_req = FALSE; }
static void start_curl_download(char *url, char *path, void (*fn)(tf_status), char *key) {
    assert(!strcmp(url, path) && !key && !finished);
    downloads++;
    finished = fn;
}
static void g_idle_add_fixture(gboolean (*fn)(gpointer), gpointer data) {
    assert(!data && !idle);
    idle = fn;
}
#define g_idle_add g_idle_add_fixture
''' + defines + '\n' + '\n\n'.join(functions) + r'''
static void reset(int n, gint64 cost) {
    count = n; covitem = 0; clock_us = 0; item_us = cost;
    downloads = pending = refreshes = 0;
    cover_dl = TRUE; pdf_dl_req = FALSE; idle = NULL; finished = NULL;
    memset(seen, 0, sizeof(seen)); memset(overlays, 0, sizeof(overlays));
    for (int i = 0; i < n; i++) ready[i] = TRUE;
}
static void complete(tf_status status) {
    assert(finished);
    void (*fn)(tf_status) = finished;
    finished = NULL;
    if (status == SUCCESS) ready[covitem] = TRUE;
    fn(status);
}
static gboolean resume(void) {
    assert(idle == find_cover_for_item);
    idle = NULL;
    return find_cover_for_item(NULL);
}
int main(void) {
    reset(185, 1000);
    assert(find_cover_for_item(NULL) && covitem == COVER_BATCH_SIZE);
    while (find_cover_for_item(NULL)) {}
    assert(covitem == 185 && !cover_dl && refreshes == 1 && !downloads);
    for (int i = 0; i < count; i++) assert(seen[i] == 1 && !overlays[i]);

    reset(185, 35000);
    assert(find_cover_for_item(NULL) && covitem == 3 && clock_us == 105000);
    reset(185, 200000); /* a single slow image cannot be preempted */
    assert(find_cover_for_item(NULL) && covitem == 1);

    reset(20, 1000);
    pdf_dl_req = TRUE;
    assert(!find_cover_for_item(NULL) && covitem == 0 && pending == 1);
    assert(cover_dl && !downloads && !refreshes);
    assert(find_cover_for_item(NULL) && covitem == COVER_BATCH_SIZE);
    pdf_dl_req = TRUE; /* user input processed between groups */
    assert(!find_cover_for_item(NULL) && covitem == COVER_BATCH_SIZE && pending == 2);
    assert(!find_cover_for_item(NULL) && !cover_dl && refreshes == 1);

    reset(6, 1000);
    ready[2] = FALSE;
    assert(!find_cover_for_item(NULL) && covitem == 2 && downloads == 1);
    assert(seen[0] && seen[1] && !seen[2] && !seen[3] && cover_dl);
    complete(SUCCESS);
    assert(seen[2] && overlays[2] && covitem == 3);
    assert(!resume() && !cover_dl && refreshes == 1);
    for (int i = 0; i < count; i++) assert(seen[i] == 1);

    reset(3, 1000);
    ready[0] = FALSE;
    assert(!find_cover_for_item(NULL));
    complete(FAILURE);
    assert(!resume() && !seen[0] && seen[1] && seen[2] && !cover_dl);

    reset(1, 1000);
    ready[0] = FALSE;
    assert(!find_cover_for_item(NULL));
    pdf_dl_req = TRUE;
    complete(SUCCESS);
    assert(!idle && !cover_dl && refreshes == 1 && pending == 1);
    puts("Bookshelf batches: count/time limits, complete catalogue, PDF priority and download resume passed");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'probe.c').write_text(program)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True))
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(path / 'probe.c'), '-o', str(path / 'probe'), *flags], check=True)
    subprocess.run([str(path / 'probe')], check=True)

#include <gtk/gtk.h>
#include <dlfcn.h>
#include <string.h>
#include <assert.h>
void set_watch_cursor(void) {}
void clear_watch_cursor(void) {}
const char *dgetfixt(const char *domain,const char *msg) { const char *p=strchr(msg,4);return p?p+1:msg; }
static GtkWidget *tab;
static int combos;
static gboolean inspect_entry(gpointer unused) {
 GList *wins=gtk_window_list_toplevels();gboolean found=FALSE;
 for(GList *p=wins;p;p=p->next) if(GTK_IS_DIALOG(p->data) && gtk_widget_get_visible(p->data)) {
  found=TRUE;gtk_dialog_response(p->data,GTK_RESPONSE_CANCEL);
 }
 g_list_free(wins);assert(found);return G_SOURCE_REMOVE;
}
static void count(GtkWidget *w, gpointer data) {
 if (GTK_IS_COMBO_BOX(w) && gtk_widget_get_visible(w)) {
  GtkTreeModel *m=gtk_combo_box_get_model(GTK_COMBO_BOX(w));
  assert(m && gtk_tree_model_iter_n_children(m,NULL)>0);
  combos++;
 }
 if (GTK_IS_CONTAINER(w)) gtk_container_foreach(GTK_CONTAINER(w),count,NULL);
}
static gboolean inspect(gpointer unused) {
 GList *wins=gtk_window_list_toplevels();gboolean found=FALSE;
 for(GList *p=wins;p;p=p->next) if(GTK_IS_DIALOG(p->data) && gtk_widget_get_visible(p->data)) {
  combos=0;count(p->data,NULL);assert(combos>=2);found=TRUE;
  gtk_dialog_response(p->data,GTK_RESPONSE_CANCEL);
 }
 g_list_free(wins);assert(found);return G_SOURCE_REMOVE;
}
static void click(GtkWidget *w,gpointer target) {
 if(GTK_IS_BUTTON(w) && g_strcmp0(gtk_button_get_label(GTK_BUTTON(w)),target)==0) {
  g_timeout_add(400,g_str_has_prefix(target,"Change")?inspect_entry:inspect,NULL);gtk_button_clicked(GTK_BUTTON(w));
 }
 if(GTK_IS_CONTAINER(w))gtk_container_foreach(GTK_CONTAINER(w),click,target);
}
int main(int argc,char **argv) {
 gtk_init(&argc,&argv);
 void *lib=dlopen("/usr/lib/rpcc/librpcc_rc_gui.so",RTLD_NOW|RTLD_GLOBAL);
 if(!lib)g_error("%s",dlerror());
 void (*init)(GtkWidget*)=dlsym(lib,"init_plugin");GtkWidget *(*get)(int)=dlsym(lib,"get_tab");
 GtkWidget *window=gtk_window_new(GTK_WINDOW_TOPLEVEL);init(window);tab=get(0);
 gtk_container_add(GTK_CONTAINER(window),tab);gtk_widget_show_all(window);
 click(tab,"Set _Locale...");click(tab,"Set _Timezone...");click(tab,"Set _Keyboard...");
 GtkWidget *system=get(1);GtkWidget *second=gtk_window_new(GTK_WINDOW_TOPLEVEL);
 gtk_container_add(GTK_CONTAINER(second),system);gtk_widget_show_all(second);
 click(system,"Change _Hostname...");click(system,"Change _Password...");
 assert(((int (*)(void))dlsym(lib,"plugin_tabs"))()==4);
 g_print("Original locale/timezone/keyboard dialogs populated and closed cleanly\n");
}

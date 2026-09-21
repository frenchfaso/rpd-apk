/* Portable backend for the original Raspberry System and Display widgets. */
#include <gtk/gtk.h>
#include <gio/gio.h>
#include <string.h>
#include "rc_gui.h"
static gboolean updating;

static gboolean apply(const char *op, const char *value, gboolean privileged) {
    GError *error=NULL; gchar *out=NULL,*err=NULL;
    const gchar *root_argv[]={"/usr/bin/pkexec","/usr/libexec/rpd-system-settings",op,NULL};
    const gchar *user_argv[]={"/usr/bin/rpd-user-settings",op,value,NULL};
    GSubprocess *p=g_subprocess_newv(privileged?root_argv:user_argv,G_SUBPROCESS_FLAGS_STDIN_PIPE|G_SUBPROCESS_FLAGS_STDOUT_PIPE|G_SUBPROCESS_FLAGS_STDERR_PIPE,&error);
    gboolean ok=p && g_subprocess_communicate_utf8(p,privileged?value:NULL,NULL,&out,&err,&error) && g_subprocess_get_successful(p);
    if(!ok) {
        GtkWidget *d=gtk_message_dialog_new(main_dlg?GTK_WINDOW(main_dlg):NULL,GTK_DIALOG_MODAL,GTK_MESSAGE_ERROR,GTK_BUTTONS_CLOSE,"%s",error?error->message:(err&&*err?err:"Unable to apply setting"));
        gtk_dialog_run(GTK_DIALOG(d));gtk_widget_destroy(d);
    }
    if(p)g_object_unref(p);g_clear_error(&error);g_free(out);g_free(err);return ok;
}
static gchar *get(const char *op) {
    gchar *out=NULL;gchar *args[]={"/usr/bin/rpd-user-settings",(gchar*)op,NULL};
    if(!g_spawn_sync(NULL,args,NULL,0,NULL,NULL,&out,NULL,NULL,NULL))return g_strdup("");
    return out?g_strstrip(out):g_strdup("");
}
static void changed(GtkSwitch *w,GParamSpec *spec,gpointer data) {
    if(updating)return;
    const char *op=data;gboolean active=gtk_switch_get_active(w);
    if(!apply(op,active?"1":"0",strcmp(op,"idle")!=0 && strcmp(op,"remote")!=0)) {
        updating=TRUE;gtk_switch_set_active(w,!active);updating=FALSE;
    }
}
static void boot(GtkToggleButton *w,gpointer unused) {
    if(updating)return;
    gboolean active=gtk_toggle_button_get_active(w);
    if(!apply("boot",active?"1":"0",TRUE)) {
        updating=TRUE;gtk_toggle_button_set_active(w,!active);updating=FALSE;
    }
}
static void browser(GtkToggleButton *w,gpointer name) {
    if(!updating && gtk_toggle_button_get_active(w))apply("browser",name,FALSE);
}
static void password_valid(GtkEntry *entry,gpointer data) {
    GtkBuilder *b=data;
    const char *a=gtk_entry_get_text(GTK_ENTRY(gtk_builder_get_object(b,"pwentry1")));
    const char *c=gtk_entry_get_text(GTK_ENTRY(gtk_builder_get_object(b,"pwentry2")));
    gtk_widget_set_sensitive(GTK_WIDGET(gtk_builder_get_object(b,"passwdok")),*a && !strcmp(a,c));
}
static void password(GtkButton *button,gpointer unused) {
    GtkBuilder *b=gtk_builder_new_from_file(PACKAGE_DATA_DIR "/ui/rc_gui.ui");
    GtkWidget *d=GTK_WIDGET(gtk_builder_get_object(b,"passwddlg"));
    if(main_dlg)gtk_window_set_transient_for(GTK_WINDOW(d),GTK_WINDOW(main_dlg));
    for(int i=1;i<=2;i++) {
        gchar *id=g_strdup_printf("pwentry%d",i);GObject *e=gtk_builder_get_object(b,id);g_free(id);
        gtk_entry_set_visibility(GTK_ENTRY(e),FALSE);g_signal_connect(e,"changed",G_CALLBACK(password_valid),b);
    }
    gtk_widget_set_sensitive(GTK_WIDGET(gtk_builder_get_object(b,"passwdok")),FALSE);
    if(gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK)
        apply("password",gtk_entry_get_text(GTK_ENTRY(gtk_builder_get_object(b,"pwentry1"))),TRUE);
    gtk_widget_destroy(d);g_object_unref(b);
}
static void hostname(GtkButton *button,gpointer unused) {
    GtkBuilder *b=gtk_builder_new_from_file(PACKAGE_DATA_DIR "/ui/rc_gui.ui");
    GtkWidget *d=GTK_WIDGET(gtk_builder_get_object(b,"hostnamedlg"));
    if(main_dlg)gtk_window_set_transient_for(GTK_WINDOW(d),GTK_WINDOW(main_dlg));
    gchar *name=get("hostname");GtkEntry *entry=GTK_ENTRY(gtk_builder_get_object(b,"hnentry1"));
    gtk_entry_set_text(entry,name);g_free(name);
    if(gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK)apply("hostname",gtk_entry_get_text(entry),TRUE);
    gtk_widget_destroy(d);g_object_unref(b);
}
static void hide(GtkBuilder *b,const char *id) {
    GtkWidget *w=GTK_WIDGET(gtk_builder_get_object(b,id));
    gtk_widget_set_no_show_all(w,TRUE);gtk_widget_hide(w);
}
void load_system_tab(GtkBuilder *b) {
    updating=TRUE;
    const char *hidden[]={"hbox14","hbox16","hbox17","hbox19",NULL};
    for(int i=0;hidden[i];i++)hide(b,hidden[i]);
    g_signal_connect(gtk_builder_get_object(b,"button_pw"),"clicked",G_CALLBACK(password),NULL);
    g_signal_connect(gtk_builder_get_object(b,"button_hn"),"clicked",G_CALLBACK(hostname),NULL);
    gchar *value=get("get-autologin");GObject *w=gtk_builder_get_object(b,"sw_alogin_desk");
    gtk_switch_set_active(GTK_SWITCH(w),!strcmp(value,"1"));g_free(value);g_signal_connect(w,"notify::active",G_CALLBACK(changed),"autologin");
    value=get("get-boot");w=gtk_builder_get_object(b,"rb_desktop");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w),!strcmp(value,"1"));
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(gtk_builder_get_object(b,"rb_cli")),strcmp(value,"1")!=0);
    g_free(value);g_signal_connect(w,"toggled",G_CALLBACK(boot),NULL);
    value=get("get-browser");
    const char *names[]={"chromium","firefox"};
    for(int i=0;i<2;i++) {
        gchar *id=g_strdup_printf("rb_%s",names[i]);w=gtk_builder_get_object(b,id);g_free(id);
        gchar *path=g_find_program_in_path(names[i]);gtk_widget_set_sensitive(GTK_WIDGET(w),path!=NULL);g_free(path);
        gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w),g_str_has_prefix(value,names[i]));
        g_signal_connect(w,"toggled",G_CALLBACK(browser),(gpointer)names[i]);
    }
    g_free(value);
    const char *display_hidden[]={"hbox52","hbox53","hbox56","hbox57","hbox58",NULL};
    for(int i=0;display_hidden[i];i++)hide(b,display_hidden[i]);
    value=get("get-idle");w=gtk_builder_get_object(b,"sw_blank");
    gtk_switch_set_active(GTK_SWITCH(w),!strcmp(value,"1"));g_free(value);
    gtk_widget_set_tooltip_text(GTK_WIDGET(w),"Blank the display after 10 minutes of inactivity");
    g_signal_connect(w,"notify::active",G_CALLBACK(changed),"idle");
    const char *interface_hidden[]={"hbox24","hbox25","hbox26","hbox27","hbox28",NULL};
    for(int i=0;interface_hidden[i];i++)hide(b,interface_hidden[i]);
    value=get("get-ssh");w=gtk_builder_get_object(b,"sw_ssh");
    gtk_switch_set_active(GTK_SWITCH(w),!strcmp(value,"1"));g_free(value);
    g_signal_connect(w,"notify::active",G_CALLBACK(changed),"ssh");
    value=get("get-remote");w=gtk_builder_get_object(b,"sw_vnc");
    gtk_switch_set_active(GTK_SWITCH(w),!strcmp(value,"1"));g_free(value);
    gtk_widget_set_tooltip_text(GTK_WIDGET(w),"WayVNC on localhost:5900. Connect through an SSH tunnel.");
    g_signal_connect(w,"notify::active",G_CALLBACK(changed),"remote");
    updating=FALSE;
}

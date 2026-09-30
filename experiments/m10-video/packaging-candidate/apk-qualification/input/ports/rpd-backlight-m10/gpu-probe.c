#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s (EGL %x, GL %x)\n", __LINE__, #x, eglGetError(), glGetError()); exit(1); } } while (0)

static GLuint shader(GLenum type, const char *source)
{
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &source, NULL);
    glCompileShader(s);
    GLint ok;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[4096]; glGetShaderInfoLog(s, sizeof(log), NULL, log); fprintf(stderr, "%s\n", log); }
    CHECK(ok);
    return s;
}

static void test(EGLDisplay display, int version)
{
    EGLint cfg_attrs[] = {EGL_SURFACE_TYPE, 0, EGL_RENDERABLE_TYPE,
        version == 3 ? EGL_OPENGL_ES3_BIT : EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig cfg;
    EGLint count;
    CHECK(eglChooseConfig(display, cfg_attrs, &cfg, 1, &count) && count);
    EGLint ctx_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, version, EGL_NONE};
    EGLContext ctx = eglCreateContext(display, cfg, EGL_NO_CONTEXT, ctx_attrs);
    CHECK(ctx != EGL_NO_CONTEXT);
    CHECK(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx));
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("ES%d renderer=%s version=%s\n", version, renderer, glGetString(GL_VERSION));
    CHECK(renderer && strstr(renderer, "504"));
    GLuint tex, fbo, vbo;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    CHECK(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    const char *vs = version == 3 ? "#version 300 es\nin vec2 pos; void main(){ gl_Position=vec4(pos,0,1); }" : "attribute vec2 pos; void main(){ gl_Position=vec4(pos,0,1); }";
    const char *fs = version == 3 ? "#version 300 es\nprecision mediump float; out vec4 color; void main(){ color=vec4(1,0,0,1); }" : "precision mediump float; void main(){ gl_FragColor=vec4(1,0,0,1); }";
    GLuint vert = shader(GL_VERTEX_SHADER, vs), frag = shader(GL_FRAGMENT_SHADER, fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vert); glAttachShader(prog, frag);
    glBindAttribLocation(prog, 0, "pos"); glLinkProgram(prog);
    GLint linked; glGetProgramiv(prog, GL_LINK_STATUS, &linked); CHECK(linked);
    glUseProgram(prog);
    const GLfloat vertices[] = {-0.8f,-0.8f, 0.8f,-0.8f, 0,0.8f};
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL); glEnableVertexAttribArray(0);
    glViewport(0, 0, 64, 64);
    for (int i = 0; i < 1; i++) {
        unsigned char center[4], corner[4];
        glClearColor(0, 0, 1, 1); glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
        glReadPixels(0, 63, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
        CHECK(glGetError() == GL_NO_ERROR);
        printf("frame%d center=%u,%u,%u,%u corner=%u,%u,%u,%u\n", i, center[0], center[1], center[2], center[3], corner[0], corner[1], corner[2], corner[3]);
        CHECK(center[0] == 255 && center[1] == 0 && center[2] == 0 && center[3] == 255);
        CHECK(corner[0] == 0 && corner[1] == 0 && corner[2] == 255 && corner[3] == 255);
    }
    glDeleteBuffers(1, &vbo); glDeleteProgram(prog); glDeleteShader(vert); glDeleteShader(frag);
    glDeleteFramebuffers(1, &fbo); glDeleteTextures(1, &tex);
    CHECK(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT));
    CHECK(eglDestroyContext(display, ctx));
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    int fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC); CHECK(fd >= 0);
    struct gbm_device *gbm = gbm_create_device(fd); CHECK(gbm);
    EGLDisplay display = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    CHECK(display != EGL_NO_DISPLAY);
    EGLint major, minor; CHECK(eglInitialize(display, &major, &minor));
    CHECK(eglBindAPI(EGL_OPENGL_ES_API));
    test(display, 2); test(display, 3);
    eglTerminate(display); gbm_device_destroy(gbm); close(fd);
    puts("PASS: GLES2/GLES3 shaders and pixel readback on Adreno 504");
    return 0;
}

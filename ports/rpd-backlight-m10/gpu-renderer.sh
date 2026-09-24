# Sourced by the M10 desktop and greeter before starting the compositor.
# A real shader/pixel check catches absent drivers and Mesa/kernel mismatches.
export RPD_SOFTWARE_RENDERING=1 WLR_RENDERER=pixman LIBGL_ALWAYS_SOFTWARE=1
unset WLR_RENDER_DRM_DEVICE
if [ -c /dev/dri/renderD128 ] &&
   env -u LIBGL_ALWAYS_SOFTWARE timeout -s KILL 8 /usr/libexec/rpd-gpu-m10-probe >/dev/null 2>&1; then
    export RPD_SOFTWARE_RENDERING=0 WLR_RENDERER=gles2
    export WLR_RENDER_DRM_DEVICE=/dev/dri/renderD128
    unset LIBGL_ALWAYS_SOFTWARE
fi

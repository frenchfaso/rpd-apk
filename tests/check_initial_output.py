#!/usr/bin/env python3
"""Integration check: run manually with patched labwc and wlr-randr installed."""
import json,os,pathlib,signal,subprocess,tempfile,time
for target,requested,expected in [('HEADLESS-1',x,x) for x in ('normal','90','180','270')]+[('OTHER','90','normal'),('HEADLESS-1','invalid','normal')]:
    with tempfile.TemporaryDirectory(prefix='rpd-frame-') as tmp:
        root=pathlib.Path(tmp);(root/'config').mkdir();(root/'config/autostart').write_text('#!/bin/sh\n');(root/'config/autostart').chmod(0o755)
        env=dict(os.environ,XDG_RUNTIME_DIR=tmp,WLR_BACKENDS='headless',WLR_HEADLESS_OUTPUTS='1',WLR_RENDERER='pixman',RPD_INITIAL_OUTPUT=target,RPD_INITIAL_TRANSFORM=requested)
        log=open(root/'log','w+')
        p=subprocess.Popen(['labwc','-C',str(root/'config')],env=env,stdout=log,stderr=log,start_new_session=True)
        try:
            for _ in range(50):
                if (root/'wayland-0').exists():break
                if p.poll() is not None:raise RuntimeError('Compositor exited')
                time.sleep(.1)
            env['WAYLAND_DISPLAY']='wayland-0'
            outputs=json.loads(subprocess.check_output(['wlr-randr','--json'],env=env,timeout=3))
            assert outputs[0]['transform']==expected,outputs
            print(target,requested,'=>',expected,flush=True)
        except Exception:
            log.seek(0);print(log.read());raise
        finally:
            if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
            p.wait(timeout=5);log.close()

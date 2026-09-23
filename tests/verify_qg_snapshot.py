#!/usr/bin/env python3
"""Exercise the actual kernel snapshot reader with injected register movement/errors."""
import pathlib, subprocess, sys, tempfile
source=pathlib.Path(sys.argv[1]).read_text()
a=source.index('static const struct sample qg_samples[]')
b=source.index('static const struct kernel_param_ops qg_snapshot_ops',a)
code=r'''
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <assert.h>
#define PAGE_SIZE 4096
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
struct sample { unsigned int reg, len; };
struct kernel_param { int unused; };
static void *map=(void *)1;
static int fault, move_fifo, move_acc, reads;
static unsigned char registers[65536];
static int regmap_read(void *unused, unsigned int address, unsigned int *value) {
    if(fault) return -EIO;
    reads++;
    *value=registers[address];
    if(reads==3 && move_fifo) (*value)++;
    if(reads==4 && move_acc) (*value)++;
    return 0;
}
static int regmap_bulk_read(void *unused, unsigned int address, void *dest, unsigned int len) {
    if(fault) return -EIO;
    assert(len<=8); assert(address+len<=sizeof(registers));
    memcpy(dest,registers+address,len);return 0;
}
static int scnprintf(char *buffer,size_t size,const char *format,...) {
    va_list args;va_start(args,format);
    int n=vsnprintf(buffer,size,format,args);va_end(args);
    return n>=0 && (size_t)n>=size ? (int)size-1:n;
}
'''+source[a:b]+r'''
int main(void) {
    char buffer[PAGE_SIZE];registers[0x4808]=0x81;
    int n=qg_snapshot_get(buffer,0);
    assert(n>0 && n<PAGE_SIZE);assert(strlen(buffer)==(size_t)n);
    assert(strstr(buffer,"4808=81\n"));assert(strstr(buffer,"48af=00\n"));
    reads=0;move_fifo=1;assert(qg_snapshot_get(buffer,0)==-EAGAIN);
    reads=0;move_fifo=0;move_acc=1;assert(qg_snapshot_get(buffer,0)==-EAGAIN);
    reads=0;move_acc=0;fault=1;assert(qg_snapshot_get(buffer,0)==-EIO);
    fault=0;map=0;assert(qg_snapshot_get(buffer,0)==-ENODEV);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as temp:
    p=pathlib.Path(temp);(p/'test.c').write_text(code)
    flags=['-fsanitize=address,undefined'] if '--sanitize' in sys.argv[2:] else []
    subprocess.run(['cc','-Wall','-Wextra','-Wno-unused-parameter',*flags,str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('PASS: actual QG reader, coherent data, FIFO/accumulator changes, bus failure, missing device')

#!/usr/bin/env python3
"""Track a signed, published pmOS kernel; rebuild its matching backlight module.
Run in disposable Alpine with python3/apk-tools. Never execute upstream APKBUILD.
"""
import gzip, hashlib, io, pathlib, re, subprocess, tarfile, tempfile, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
PORT=ROOT/'ports/rpd-backlight-m10'
PACKAGE='linux-postmarketos-qcom-msm89x7'
REPO='https://mirror.postmarketos.org/postmarketos/main'
RECIPE='https://gitlab.postmarketos.org/postmarketOS/pmaports/-/raw/main/device/testing/'+PACKAGE+'/APKBUILD'

def field(text, name):
    return re.search(r'^'+re.escape(name)+r'=(.+)$',text,re.M)[1].strip('"')

def recipe_shape(text):
    text=re.sub(r'^(pkgver|pkgrel)=.*$',r'\1=<version>',text,flags=re.M)
    return re.sub(r'^[0-9a-f]{128}  ', '<checksum>  ', text,flags=re.M)

def read_package(path):
    # APK v2 contains concatenated gzip/tar members. No files are extracted.
    raw=gzip.decompress(path.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:',ignore_zeros=True) as tar:
        names={m.name.removeprefix('./'):m for m in tar.getmembers() if m.isfile()}
        return (tar.extractfile(names['.PKGINFO']).read().decode(),
                tar.extractfile(names['boot/config']).read().decode())

def main():
    with tempfile.TemporaryDirectory() as temp:
        dest=pathlib.Path(temp)
        subprocess.run(['apk','--arch','aarch64','--keys-dir',str(ROOT/'keys'),
            '--repositories-file','/dev/null','--repository',REPO,
            '--no-cache','fetch','--from','none','--output',temp,PACKAGE],check=True)
        package,=dest.glob(PACKAGE+'-*.apk')
        # apk fetch authenticates the signed repository index, then checks the
        # package control digest and data hash against that trusted identity.
        # A standalone `apk verify` demands the original builder's signature,
        # which need not be the repository signing key. Never use allow-untrusted.
        # See apk-tools app_fetch.c: apk_extract_verify_identity + apk_extract.
        info,config=read_package(package)
    version=re.search(r'^pkgver = (\S+)$',info,re.M)[1]
    if not re.fullmatch(r'\d+(?:\.\d+)+-r\d+',version):
        raise ValueError('Kernel version format requires review: '+version)
    text=(PORT/'APKBUILD').read_text()
    previous=re.search(PACKAGE+r'=(\S+)',text)[1]
    if version==previous:
        if config != (PORT/'kernel.config').read_text():
            raise ValueError('Published kernel config changed without an APK version bump')
        print('Authenticated pmOS kernel unchanged: '+version)
        return
    if subprocess.check_output(['apk','version','-t',version,previous],text=True).strip()!='>':
        raise ValueError('Published kernel version regressed')
    with urllib.request.urlopen(RECIPE,timeout=90) as response:
        recipe=response.read().decode()
    if field(recipe,'pkgver')+'-r'+field(recipe,'pkgrel')!=version:
        raise ValueError('Published binary and upstream recipe differ; defer until matched')
    if recipe_shape(recipe)!=recipe_shape((PORT/'upstream-APKBUILD.reference').read_text()):
        raise ValueError('Kernel recipe changed beyond versions/checksums; review required')
    pkgver=field(recipe,'pkgver')
    # The reviewed recipe uses _tag="$pkgver-r1", no extra source patches.
    source_hash=re.search(r'^([0-9a-f]{128})  linux-postmarketos-qcom-msm89x7-',recipe,re.M)[1]
    release=re.search(r'^CONFIG_LOCALVERSION="([^"]+)"$',config,re.M)[1]
    release=pkgver+release
    if not re.fullmatch(r'\d+(?:\.\d+)+-msm89x7',release):
        raise ValueError('Kernel release/flavor changed')
    clang=int(re.search(r'^CONFIG_CLANG_VERSION=(\d+)$',config,re.M)[1])//10000
    if not 20 <= clang <= 99:
        raise ValueError('Compiler needs review')
    oldver=field(text,'pkgver')
    text=text.replace(oldver,pkgver)
    text=re.sub(PACKAGE+r'=[^ ]+',PACKAGE+'='+version,text)
    text=re.sub(r'clang\d+ lld\d+ llvm\d+',f'clang{clang} lld{clang} llvm{clang}',text)
    text=re.sub(r'/usr/lib/llvm\d+/bin',f'/usr/lib/llvm{clang}/bin',text)
    text=re.sub(r'^pkgrel=\d+$','pkgrel='+('0' if pkgver!=oldver else str(int(field(text,'pkgrel'))+1)),text,flags=re.M)
    text=re.sub(r'^[0-9a-f]{128}(  linux-v[^\n]+)$',source_hash+r'\1',text,flags=re.M)
    (PORT/'kernel.config').write_text(config)
    for name in ['rpd-backlight-m10-load','rpd-backlight-m10.post-install','rpd-backlight-m10.post-upgrade']:
        p=PORT/name
        p.write_text(re.sub(r'\d+(?:\.\d+)+-msm89x7',release,p.read_text()))
    for name in ['kernel.config','rpd-backlight-m10-load']:
        digest=hashlib.sha512((PORT/name).read_bytes()).hexdigest()
        text=re.sub(r'^[0-9a-f]{128}  '+re.escape(name)+r'$',digest+'  '+name,text,flags=re.M)
    (PORT/'APKBUILD').write_text(text)
    (PORT/'upstream-APKBUILD.reference').write_text(recipe)
    print('Prepared matching backlight rebuild for authenticated kernel '+version)

if __name__=='__main__':main()

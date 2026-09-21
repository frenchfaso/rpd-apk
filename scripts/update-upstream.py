#!/usr/bin/env python3
"""Follow published Raspberry Trixie sources; verify signatures and content hashes."""
import argparse,gzip,hashlib,io,json,pathlib,re,subprocess,tarfile,tempfile,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='https://archive.raspberrypi.com/debian/'
FINGERPRINT='CF8A1AF502A2AA2D763BAE7E82B129927FA3303E'
def fetch(url):
    if not url.startswith(BASE): raise ValueError('Unapproved upstream URL')
    with urllib.request.urlopen(url,timeout=90) as r:return r.read()
def paragraphs(text):
    for block in text.split('\n\n'):
        d={};key=None
        for line in block.splitlines():
            if line.startswith(' ') and key:d[key]+='\n'+line.strip()
            elif ':' in line:key,value=line.split(':',1);d[key]=value.strip()
        if d:yield d

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    lockpath=ROOT/'upstream.lock.json';old=json.loads(lockpath.read_text());new={}
    with tempfile.TemporaryDirectory() as temp:
        t=pathlib.Path(temp);t.chmod(0o700)
        key=ROOT/'keys/raspberrypi-archive.asc'
        info=subprocess.check_output(['gpg','--homedir',temp,'--with-colons','--show-keys',str(key)],stderr=subprocess.DEVNULL).decode()
        if FINGERPRINT not in info:raise ValueError('Unexpected archive signing key')
        subprocess.run(['gpg','--homedir',temp,'--batch','--import',str(key)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        signed=t/'InRelease';signed.write_bytes(fetch(BASE+'dists/trixie/InRelease'))
        release=subprocess.check_output(['gpg','--homedir',temp,'--batch','--no-auto-key-retrieve','--decrypt',str(signed)]).decode()
        release_fields=next(paragraphs(release))
        index_path='main/source/Sources.gz'
        rows=[line.split() for line in release_fields['SHA256'].splitlines() if line.strip()]
        expected,size,_=next(x for x in rows if x[2]==index_path)
        packed=fetch(BASE+'dists/trixie/'+index_path)
        if len(packed)!=int(size) or hashlib.sha256(packed).hexdigest()!=expected:raise ValueError('Source index checksum mismatch')
        records={d['Package']:d for d in paragraphs(gzip.decompress(packed).decode())}
        for name,previous in old.items():
            record=records[name];version=record['Version']
            if not re.fullmatch(r'\d+(?:\.\d+)*',version):raise ValueError('Version format requires review: '+version)
            if tuple(map(int,version.split('.')))<tuple(map(int,previous['version'].split('.'))):raise ValueError('Upstream version regressed')
            entries=[x.split() for x in record['Checksums-Sha256'].splitlines() if '.tar.' in x]
            if len(entries)!=1:raise ValueError('Non-native source layout requires a packaging change')
            sha,size,filename=entries[0]
            if version==previous['version']:
                if sha!=previous['sha256']:raise ValueError('Published archive changed without version bump: '+name)
                new[name]=previous;continue
            directory=record['Directory']
            if not re.fullmatch(r'pool/[a-z0-9/+-]+',directory) or '/' in filename:raise ValueError('Unsafe source path')
            url=BASE+directory+'/'+filename;data=fetch(url)
            if len(data)!=int(size) or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Archive checksum mismatch')
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                roots={n.split('/')[0] for n in archive.getnames()}
                if len(roots)!=1 or not re.fullmatch(r'[a-zA-Z0-9_.+-]+',next(iter(roots))):raise ValueError('Unexpected archive root')
            new[name]=dict(version=version,url=url,sha256=sha,sha512=hashlib.sha512(data).hexdigest(),filename=filename,directory=next(iter(roots)),pkgrel=0)
    changed=new!=old
    print('New published sources found' if changed else 'Published sources unchanged; signature verified')
    if changed and not args.check:
        lockpath.write_text(json.dumps(new,indent=2)+'\n')
        subprocess.run(['python3',str(ROOT/'scripts/generate.py')],check=True)
    if args.check and changed:raise SystemExit(2)
if __name__=='__main__':main()

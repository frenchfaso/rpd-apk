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
            record=records[name];source_version=record['Version']
            old_source=previous.get('source_version',previous['version'])
            # Debian orders epochs and packaging revisions, including quilt sources.
            comparison=subprocess.run(['dpkg','--compare-versions',source_version,'lt',old_source]).returncode
            if comparison not in (0,1):raise ValueError('Invalid Debian version: '+name)
            if comparison==0:raise ValueError('Upstream version regressed: '+name)
            version=source_version.split(':')[-1]
            quilt='debian' in previous
            if quilt:version=version.rsplit('-',1)[0]
            if name=='qtstyleplugins-src':
                match=re.fullmatch(r'(\d+(?:\.\d+)*)\+git(\d+)\.g[0-9a-f]+',version)
                if not match:raise ValueError('Qt style source version requires review')
                version=match[1]+'_git'+match[2]
            elif not re.fullmatch(r'\d+(?:\.\d+)*',version):raise ValueError('Version format requires review: '+version)
            if tuple(map(int,re.findall(r'\d+',version)))<tuple(map(int,re.findall(r'\d+',previous['version']))):
                raise ValueError('APK version would regress; epoch mapping requires review: '+name)
            entries=[x.split() for x in record['Checksums-Sha256'].splitlines() if '.tar.' in x]
            if len(entries)!=(2 if quilt else 1):raise ValueError('Source layout changed: '+name)
            if quilt:
                orig=[x for x in entries if '.orig.tar.' in x[2]]
                deb=[x for x in entries if '.debian.tar.' in x[2]]
                if len(orig)!=1 or len(deb)!=1:raise ValueError('Quilt source layout changed')
                entries=orig+deb
            if source_version==old_source:
                pinned=[previous,previous['debian']] if quilt else [previous]
                for (sha,size,filename),saved in zip(entries,pinned):
                    if sha!=saved['sha256'] or filename!=saved['filename']:
                        raise ValueError('Published archive changed without version bump: '+name)
                new[name]=previous;continue
            directory=record['Directory'];downloaded=[]
            if not re.fullmatch(r'pool/[a-z0-9/+-]+',directory):raise ValueError('Unsafe source path')
            for sha,size,filename in entries:
                if '/' in filename:raise ValueError('Unsafe source filename')
                url=BASE+directory+'/'+filename;data=fetch(url)
                if len(data)!=int(size) or hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Archive checksum mismatch')
                with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                    roots={n.split('/')[0] for n in archive.getnames()}
                    if len(roots)!=1 or not re.fullmatch(r'[a-zA-Z0-9_.+-]+',next(iter(roots))):raise ValueError('Unexpected archive root')
                downloaded.append((dict(url=url,sha256=sha,sha512=hashlib.sha512(data).hexdigest(),filename=filename),next(iter(roots))))
            metadata,root=downloaded[0]
            new[name]=dict(metadata,version=version,source_version=source_version,directory=root,
                           pkgrel=previous['pkgrel'] if version==previous['version'] else 0)
            if quilt:
                if downloaded[1][1]!='debian':raise ValueError('Unexpected Debian archive root')
                new[name]['debian']=downloaded[1][0]
    # A new dependency is not automatically safe/portable merely because its
    # containing metapackage has a newer version. Require explicit review.
    meta=new['rpd-metas'];data=fetch(meta['url'])
    if hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('Metapackage checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        control=archive.extractfile(meta['directory']+'/debian/control').read().decode()
    components={}
    for record in paragraphs(control):
        if 'Package' not in record:continue
        names=[]
        for item in re.split(r'[,|]',record.get('Depends','')+','+record.get('Recommends','')):
            match=re.match(r'\s*([a-z0-9][a-z0-9+.-]*)',item)
            if match:names.append(match[1])
        components[record['Package']]=sorted(set(names))
    reviewed=json.loads((ROOT/'upstream-desktop-components.json').read_text())
    if components!=reviewed:raise ValueError('Official desktop component set changed; review upstream-desktop-components.json before release')
    changed=new!=old
    print('New published sources found' if changed else 'Published sources unchanged; signature verified')
    if changed and not args.check:
        lockpath.write_text(json.dumps(new,indent=2)+'\n')
        subprocess.run(['python3',str(ROOT/'scripts/generate.py')],check=True)
    if args.check and changed:raise SystemExit(2)
if __name__=='__main__':main()

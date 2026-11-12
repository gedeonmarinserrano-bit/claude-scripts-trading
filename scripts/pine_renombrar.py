import re, sys
src, dst = sys.argv[1], sys.argv[2]
t = open(src, encoding='utf-8').read()
L = t.split('\n')
# separar código y cadenas
def trozos(line):
    out=[]; i=0; buf=''; q=None
    for ch in line:
        if q:
            buf+=ch
            if ch==q: out.append(('s',buf)); buf=''; q=None
        elif ch in '"\'':
            if buf: out.append(('c',buf))
            buf=ch; q=ch
        else: buf+=ch
    if buf: out.append(('s' if q else 'c',buf))
    return out
code_only='\n'.join(''.join(b for k,b in trozos(l) if k=='c') for l in L if not l.startswith('//'))
ident=re.compile(r'[A-Za-z_]\w*')
decl=set()
for l in code_only.split('\n'):
    m=re.match(r'^\t*(?:var\s+|varip\s+)?(?:[\w.]+(?:<[\w.<>, ]+>)?\s+)?([A-Za-z_]\w*)(?::)?=(?!=)',l)
    if m: decl.add(m.group(1))
    m=re.match(r'^\t*\[([\w, ]+)\]=',l)
    if m: decl.update(x.strip() for x in m.group(1).split(','))
    m=re.match(r'^([A-Za-z_]\w*)\(([^)]*)\)=>',l)
    if m:
        decl.add(m.group(1))
        for p in m.group(2).split(','):
            p=p.strip()
            if p: decl.add(re.split(r'[\s=]',p.split('=')[0].strip())[-1])
    for m in re.finditer(r'\bfor\s+([A-Za-z_]\w*)\s*(?:=|in\b)',l): decl.add(m.group(1))
    m=re.match(r'^\t*for\s*\[([\w, ]+)\]\s*in',l)
    if m: decl.update(x.strip() for x in m.group(1).split(','))
# campos de tipos
lines=code_only.split('\n')
for i,l in enumerate(lines):
    if re.match(r'^type \w+',l):
        j=i+1
        while j<len(lines) and lines[j].startswith('\t'):
            m=re.match(r'^\t[\w.<>]+\s+([A-Za-z_]\w*)',lines[j])
            if m: decl.add(m.group(1))
            j+=1
named=set(re.findall(r'[(,]\s*([A-Za-z_]\w*)=(?!=)',code_only))
kw={'and','or','not','if','else','for','to','by','in','while','var','varip','true','false','na','type','import','export','method','switch','continue','break','int','float','bool','string','color','line','label','box','table','array','matrix','map','series','simple','const'}
cands=[n for n in decl if len(n)>=4 and n not in named and n not in kw]
freq={n:len(re.findall(r'\b'+re.escape(n)+r'\b',code_only)) for n in cands}
cands.sort(key=lambda n:-(len(n)-3)*freq[n])
existing=set(ident.findall(code_only))
import itertools, string
def nombres():
    al=string.ascii_lowercase
    for k in itertools.count(1):
        for tup in itertools.product(al,repeat=k):
            yield '_'+''.join(tup)
gen=nombres(); ren={}
for n in cands:
    new=next(gen)
    while new in existing: new=next(gen)
    if len(new)<len(n): ren[n]=new
pat=re.compile(r'\b('+'|'.join(map(re.escape,sorted(ren,key=len,reverse=True)))+r')\b')
out=[]
for l in L:
    if l.startswith('//'): out.append(l); continue
    out.append(''.join(pat.sub(lambda m:ren[m.group(1)],b) if k=='c' else b for k,b in trozos(l)))
r='\n'.join(out)
open(dst,'w',encoding='utf-8').write(r)
print(len(t),'->',len(r),'renamed',len(ren))

import sys
src, dst = sys.argv[1], sys.argv[2]
L = open(src, encoding='utf-8').read().split('\n')
def sin_comentario(l):
    q = None
    for i, ch in enumerate(l):
        if q:
            if ch == q: q = None
        elif ch in '"\'':
            q = ch
        elif l.startswith('//', i):
            return l[:i].rstrip()
    return l.rstrip()
out = []
PUNT = set(',()[]=+-*/%?:')
cabecera = True
for l in L:
    st = l.strip()
    if cabecera:
        if st.startswith('//@version'):
            out.append(st); cabecera = False
        elif st.startswith('//') and ('©' in st or 'licen' in st.lower() or 'creativecommons' in st or st.startswith('// Po3')):
            out.append(st)
        continue
    if st.startswith('//@'):
        out.append(st); continue
    if not st or st.startswith('//'):
        continue
    c = sin_comentario(l)
    if not c.strip():
        continue
    n = len(c) - len(c.lstrip(' '))
    cuerpo = c.lstrip(' ')
    # espacios múltiples fuera de cadenas -> uno
    r = []; q = None; prev = ''
    for ch in cuerpo:
        if q:
            r.append(ch)
            if ch == q: q = None
        else:
            if ch in '"\'': q = ch
            if ch == ' ' and prev == ' ':
                continue
            if ch == ' ' and prev in PUNT:
                continue
            if ch in PUNT and r and r[-1] == ' ' and (len(r) < 2 or r[-2] not in '<>'):
                r.pop()
            r.append(ch)
        prev = ch
    out.append('\t' * (n // 4) + ''.join(r))
t = '\n'.join(out) + '\n'
open(dst, 'w', encoding='utf-8').write(t)
print(len(t), len(out))

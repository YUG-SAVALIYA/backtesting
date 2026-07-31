import re
src = open('static/index.html', encoding='utf-8').read()
bt = re.search(r'id="backtestView"[^>]*>', src)
lv = re.search(r'id="liveView"[^>]*>', src)
print('backtestView tag:', bt.group() if bt else 'NOT FOUND')
print('liveView tag:    ', lv.group() if lv else 'NOT FOUND')
sm = [l.strip() for l in src.split('\n') if 'switchMainTab' in l or 'backtestView.style' in l or 'liveView.style' in l]
for l in sm[:20]:
    print(repr(l))

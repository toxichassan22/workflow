import app, json

slides_full = [{'title': f'الشريحة {i}', 'html': f'<div class="slide slide-{i}">' + ('<p>محتوى تفصيلي للشريحة</p>' * 8) + '</div>'} for i in range(1, 17)]
valid = json.dumps({'slides': slides_full}, ensure_ascii=False)

# CASE 1: fully valid
r1 = app.extract_slides_recover(valid)
assert len(r1) == 16, 'valid 16-slide fail: got %d' % len(r1)
assert r1[0]['title'] == 'الشريحة 1' and r1[15]['title'] == 'الشريحة 16'
print('  valid 16 slides ->', len(r1), 'OK')

# CASE 2: truncated mid-stream (slide 12 cut off)
arr_text = ', '.join(json.dumps(s, ensure_ascii=False) for s in slides_full[:11])
truncated = '{"slides": [' + arr_text + ', {"title": "الشريحة 12", "html": "<div class=slide>بدء محتوى الشريحة الـ12 ثم ينقطع هنا بدون ا'
r2 = app.extract_slides_recover(truncated)
print('  truncated (slide 12 cut) -> recovered', len(r2), 'slides')
assert len(r2) == 11, 'expected 11 complete slides, got %d' % len(r2)
assert r2[-1]['title'] == 'الشريحة 11'
print('  recovered slides 1..11, partial 12 dropped OK')

# CASE 3: severely truncated
arr3 = ', '.join(json.dumps(s, ensure_ascii=False) for s in slides_full[:3])
sev = '{"slides": [' + arr3 + ', {"title":"x","html":"<div>cu'
r3 = app.extract_slides_recover(sev)
assert len(r3) == 3, 'severe fail: got %d' % len(r3)
print('  severe truncation -> recovered', len(r3), 'OK')

# CASE 4: wrapped in json fences and truncated
fenced = '```json\n' + truncated + '\n```'
r4 = app.extract_slides_recover(fenced)
assert len(r4) == 11, 'fenced fail: got %d' % len(r4)
print('  fenced+truncated -> recovered', len(r4), 'OK')

# CASE 5: empty/garbage
assert app.extract_slides_recover('') == []
assert app.extract_slides_recover('no json at all') == []
assert app.extract_slides_recover('{"foo":"bar"}') == []
print('  garbage inputs -> [] OK')

# CASE 6: dedupe by (title, html). Build a TRUNCATED stream so the recovery
# path runs (not the fast path), then embed the SAME slide twice so the bare
# scan sees it both as a nested object and again bare — the dedupe must
# collapse the exact duplicate while keeping the distinct slide.
same = {'title': 'a', 'html': '<div class="a">X</div>'}
other = {'title': 'b', 'html': '<div class="b">Y</div>'}
# wrapper is unclosed (truncated) → forces recovery path; 'same' appears twice.
dup = '{"slides": [' + json.dumps(same, ensure_ascii=False) + ', ' + json.dumps(same, ensure_ascii=False) + ', ' + json.dumps(other, ensure_ascii=False) + ', {"title":"c","html":"<div class=c>cu'
r6 = app.extract_slides_recover(dup)
titles = [s['title'] for s in r6]
assert titles == ['a', 'b'], 'dedupe fail: got %r' % titles
print('  dedupe collapses exact dup, keeps distinct OK ->', titles)

# CASE 6b: distinct slides that happen to share identical html (reused
# template) but differ in title must BOTH survive dedupe.
t1 = {'title': 'intro', 'html': '<div class="cover">TITLE</div>'}
t2 = {'title': 'outro', 'html': '<div class="cover">TITLE</div>'}
dup2 = '{"slides": [' + json.dumps(t1, ensure_ascii=False) + ', ' + json.dumps(t2, ensure_ascii=False) + ', {"title":"x","html":"<div>cu'
r6b = app.extract_slides_recover(dup2)
assert len(r6b) == 2, 'shared-html distinct titles must both survive: got %d' % len(r6b)
print('  shared-html distinct titles kept OK ->', [s['title'] for s in r6b])

print('\nALL RECOVERY TESTS PASSED')

import json
import os
import fitz
from PIL import Image, ImageDraw, ImageFont

root = r'd:\workflow\examples'
out = r'd:\workflow\.tmp_examples_review'
os.makedirs(out, exist_ok=True)
manifest = []
font = ImageFont.load_default()

for file_index, name in enumerate(sorted(os.listdir(root)), 1):
    path = os.path.join(root, name)
    doc = fitz.open(path)
    item = {'index': file_index, 'name': name, 'pages': len(doc), 'sheets': []}
    text_parts = []
    page_images = []
    for page_index, page in enumerate(doc):
        text_parts.append(f'\n===== PAGE {page_index + 1} =====\n{page.get_text("text")}')
        pix = page.get_pixmap(matrix=fitz.Matrix(0.34, 0.34), alpha=False)
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        page_images.append(img)
    text_name = f'pdf_{file_index:02d}_text.txt'
    with open(os.path.join(out, text_name), 'w', encoding='utf-8') as handle:
        handle.write(''.join(text_parts))
    item['text'] = text_name
    cols = 4
    rows = 3
    cell_w = 340
    cell_h = 245
    for sheet_index, start in enumerate(range(0, len(page_images), cols * rows), 1):
        canvas = Image.new('RGB', (cols * cell_w, rows * cell_h), 'white')
        draw = ImageDraw.Draw(canvas)
        for local_index, img in enumerate(page_images[start:start + cols * rows]):
            col = local_index % cols
            row = local_index // cols
            x = col * cell_w
            y = row * cell_h
            draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline=(180, 180, 180), width=1)
            draw.text((x + 6, y + 4), f'Page {start + local_index + 1}', fill='black', font=font)
            fitted = img.copy()
            fitted.thumbnail((cell_w - 12, cell_h - 28), Image.Resampling.LANCZOS)
            px = x + (cell_w - fitted.width) // 2
            py = y + 24 + (cell_h - 28 - fitted.height) // 2
            canvas.paste(fitted, (px, py))
        sheet_name = f'pdf_{file_index:02d}_sheet_{sheet_index:02d}.jpg'
        canvas.save(os.path.join(out, sheet_name), quality=88)
        item['sheets'].append(sheet_name)
    manifest.append(item)

with open(os.path.join(out, 'manifest.json'), 'w', encoding='utf-8') as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
print(json.dumps(manifest, ensure_ascii=False, indent=2))

from pathlib import Path

source = Path("index.html").read_text(encoding="utf-8").splitlines()
patterns = (
    "designer-chat",
    "DesignerChat",
    "designerChat",
    "CLIENT_REQUEST_TIMEOUT",
    "sendTenantDesigner",
    "tenantDesigner",
    "slidesData",
)
windows = []
for index, line in enumerate(source):
    if any(pattern in line for pattern in patterns):
        windows.append((max(0, index - 80), min(len(source), index + 121)))

merged = []
for start, end in sorted(windows):
    if merged and start <= merged[-1][1] + 5:
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    else:
        merged.append((start, end))

output = []
for start, end in merged:
    output.append(f"===== index.html lines {start + 1}-{end} =====")
    output.extend(f"{number + 1:06d}: {source[number]}" for number in range(start, end))
    output.append("")

Path("tmp").mkdir(exist_ok=True)
Path("tmp/designer_context.txt").write_text("\n".join(output), encoding="utf-8")

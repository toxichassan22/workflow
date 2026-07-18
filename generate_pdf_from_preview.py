import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def generate_pdf():
    # Paths
    project_root = Path("D:/workflow").resolve()
    preview_path = project_root / "preview.html"
    resolved_html_path = project_root / "preview_resolved.html"
    output_pdf_path = project_root / "outputs" / "برج_المملكة_ريزيدنس.pdf"

    # Ensure output directory exists
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Reading {preview_path}...")
    with open(preview_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Define the custom CSS overrides including fonts and print styles
    custom_style = """
    @font-face {
        font-family: 'The Sans Arabic';
        src: url('file:///D:/workflow/assets/fonts/TheSansArabic-Light.otf') format('opentype');
        font-weight: normal;
        font-style: normal;
    }
    @font-face {
        font-family: 'The Sans Arabic';
        src: url('file:///D:/workflow/assets/fonts/BahijTheSansArabic-Bold.ttf') format('truetype');
        font-weight: bold;
        font-style: normal;
    }
    @font-face {
        font-family: 'The Sans Arabic';
        src: url('file:///D:/workflow/assets/fonts/BahijTheSansArabic-Bold.ttf') format('truetype');
        font-weight: 700;
        font-style: normal;
    }
    @font-face {
        font-family: 'The Sans Arabic';
        src: url('file:///D:/workflow/assets/fonts/BahijTheSansArabic-Bold.ttf') format('truetype');
        font-weight: 600;
        font-style: normal;
    }

    @media print {
        body {
            background: white !important;
            margin: 0 !important;
            padding: 0 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }
        .slide {
            margin: 0 !important;
            border: none !important;
            page-break-after: always !important;
            page-break-inside: avoid !important;
            width: 1280px !important;
            height: 720px !important;
            box-shadow: none !important;
        }
        .slide:last-child {
            page-break-after: auto !important;
        }
    }
    """

    # Inject the style block before </head>
    if "</head>" in html:
        html = html.replace("</head>", f"<style>{custom_style}</style></head>")
    else:
        html = html + f"<style>{custom_style}</style>"

    # Replace placeholders with absolute paths
    html = html.replace("##LOGO##", "file:///D:/workflow/assets/logo.png")
    html = html.replace("##IMAGE_COVER##", "file:///D:/workflow/uploads/luxury_skyscraper_cover.png")
    html = html.replace("##MOODBOARD_IMAGE_1##", "file:///D:/workflow/uploads/moodboard_exterior.png")
    html = html.replace("##MOODBOARD_IMAGE_2##", "file:///D:/workflow/uploads/moodboard_interior.png")
    html = html.replace("##MOODBOARD_IMAGE_3##", "file:///D:/workflow/uploads/moodboard_materials.png")
    html = html.replace("##MOODBOARD_IMAGE_4##", "file:///D:/workflow/uploads/moodboard_urban_lifestyle.png")

    # Replace relative paths starting with uploads/ or assets/ with absolute file URIs
    # (handles cases like src="uploads/..." or src='uploads/...')
    html = html.replace('"uploads/', '"file:///D:/workflow/uploads/')
    html = html.replace("'uploads/", "'file:///D:/workflow/uploads/")
    html = html.replace('url("uploads/', 'url("file:///D:/workflow/uploads/')
    html = html.replace("url('uploads/", "url('file:///D:/workflow/uploads/")
    html = html.replace('url(uploads/', 'url(file:///D:/workflow/uploads/')

    html = html.replace('"assets/', '"file:///D:/workflow/assets/')
    html = html.replace("'assets/", "'file:///D:/workflow/assets/")
    html = html.replace('url("assets/', 'url("file:///D:/workflow/assets/')
    html = html.replace("url('assets/", "url('file:///D:/workflow/assets/")
    html = html.replace('url(assets/', 'url(file:///D:/workflow/assets/')

    print(f"Writing resolved HTML to {resolved_html_path}...")
    with open(resolved_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("Launching Playwright to generate PDF...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--font-render-hinting=none"
            ]
        )
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})

        # Load the local HTML file
        file_url = resolved_html_path.as_uri()
        print(f"Loading {file_url}...")
        page.goto(file_url, wait_until="networkidle")

        # Wait for fonts to load
        print("Waiting for fonts to load...")
        page.evaluate("() => document.fonts.ready")
        page.wait_for_timeout(1500)  # Extra buffer to settle rendering/images

        # Generate the PDF
        print(f"Printing PDF to {output_pdf_path.name.encode('ascii', errors='replace').decode('ascii')}...")
        page.pdf(
            path=str(output_pdf_path),
            width="1280px",
            height="720px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
        )
        browser.close()

    print("PDF generation complete!")
    return str(output_pdf_path)

if __name__ == "__main__":
    generate_pdf()

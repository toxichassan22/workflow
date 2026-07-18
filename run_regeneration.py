import os
import json
import re
import sys
from app import app
import db
import maps_service

# Reconfigure stdout to print utf-8 safely
sys.stdout.reconfigure(encoding='utf-8')

pres_id = 'e7f25d8f-f679-4d1d-aa02-f65740bb78f1'

with app.app_context():
    conn = db.get_db()
    pres = conn.execute("SELECT tenant_id, project_data, slides_data FROM presentations WHERE id = ?", (pres_id,)).fetchone()
    if not pres:
        print("Presentation not found")
        sys.exit(1)
    
    tenant_id, project_data_str, slides_data_str = pres
    project_data = json.loads(project_data_str) if project_data_str else {}
    slides_data = json.loads(slides_data_str) if slides_data_str else []
    
    print(f"Generating map images for tenant {tenant_id} and presentation {pres_id}...")
    result = maps_service.generate_all_map_images(project_data, tenant_id, presentation_id=pres_id, force=True)
    if result.get('error'):
        print("Error generating map images:", result['error'])
        sys.exit(1)
        
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = f"/{rel_path}"
        else:
            placeholders[placeholder] = None

    if slides_data:
        slides_json = json.dumps(slides_data, ensure_ascii=False)
        updated = False
        for placeholder, rel_path in placeholders.items():
            if not rel_path:
                continue
            ptype = placeholder.replace('##MAP_', '').replace('##STREET_VIEW_', 'streetview_').replace('##', '').lower()
            pattern = r'/uploads/maps/[^/]+_[^/]+_' + ptype + r'_[^/]+\.png'
            if re.search(pattern, slides_json):
                slides_json = re.sub(pattern, rel_path, slides_json)
                updated = True
        if updated:
            slides_data = json.loads(slides_json)
            db.update_presentation(pres_id, slides_data=slides_data)
            print("Successfully updated presentation slides with new map paths")
        else:
            print("No slide map paths were updated (placeholders not found in slides_data)")

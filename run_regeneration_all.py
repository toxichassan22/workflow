import os
import sys

# Ensure we can import app and maps_service
sys.path.append(os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

import json
import re
import uuid
import sqlite3

# Reconfigure stdout to print utf-8 safely
sys.stdout.reconfigure(encoding='utf-8')

import db
import maps_service
from app import app

print("Starting Map Regeneration for all presentations in database...")

with app.app_context():
    conn = db.get_db()
    presentations = conn.execute("SELECT id, tenant_id, title, project_data, slides_data FROM presentations").fetchall()
    
    print(f"Found {len(presentations)} presentations to process.\n")
    
    for row in presentations:
        pres_id = row['id']
        tenant_id = row['tenant_id']
        title = row['title']
        project_data_str = row['project_data']
        slides_data_str = row['slides_data']
        
        print(f"============================================================")
        print(f"Processing presentation: '{title}'")
        print(f"ID: {pres_id} | Tenant: {tenant_id}")
        print(f"============================================================")
        
        project_data = json.loads(project_data_str) if project_data_str else {}
        slides_data = json.loads(slides_data_str) if slides_data_str else []
        
        # Ensure coordinates are present
        lat = project_data.get('location_lat')
        lng = project_data.get('location_lng')
        if lat is None or lng is None:
            print("Skipping: Presentation does not have location coordinates.")
            continue
            
        print(f"Location found: {lat}, {lng}")
        
        # Force enable all map types to generate the complete suite
        project_data['enabled_maps'] = ['overview', 'landmarks', 'access', 'catchment', 'streetview']
        project_data['auto_detect_site_polygon'] = True
        
        # Set default styles if not set
        if 'map_styles' not in project_data:
            project_data['map_styles'] = {
                'overview': 'satellite',
                'landmarks': 'satellite',
                'access': 'satellite',
                'catchment': 'satellite',
                'streetview': 'satellite'
            }
            
        print("Calling generate_all_map_images (force=True)...")
        result = maps_service.generate_all_map_images(project_data, tenant_id, presentation_id=pres_id, force=True)
        if result.get('error'):
            print(f"Error generating maps: {result['error']}")
            continue
            
        # Convert absolute paths to public URLs
        placeholders = {}
        for placeholder, path in result.get('placeholders', {}).items():
            if path and os.path.exists(path):
                rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
                placeholders[placeholder] = f"/{rel_path}"
                print(f"  Generated placeholder: {placeholder} -> /{rel_path}")
            else:
                placeholders[placeholder] = None
                
        # Update slide data templates
        if slides_data:
            slides_json = json.dumps(slides_data, ensure_ascii=False)
            updated = False
            for placeholder, rel_path in placeholders.items():
                if not rel_path:
                    continue
                # 1. Match typical generated map paths in database
                ptype = placeholder.replace('##MAP_', '').replace('##STREET_VIEW_', 'streetview_').replace('##', '').lower()
                pattern = r'/uploads/maps/[^/]+_[^/]+_' + ptype + r'_[^/]+\.png'
                if re.search(pattern, slides_json):
                    slides_json = re.sub(pattern, rel_path, slides_json)
                    updated = True
                # 2. Match raw placeholder strings if they exist
                if placeholder in slides_json:
                    slides_json = slides_json.replace(placeholder, rel_path)
                    updated = True
            
            if updated:
                slides_data = json.loads(slides_json)
                db.update_presentation(pres_id, slides_data=slides_data)
                print("Successfully updated database with new map slide links!")
            else:
                print("Note: No path changes were detected in the slide HTML templates.")
        else:
            print("Note: No slides_data found for this presentation.")
            
print("\nAll presentations successfully processed!")

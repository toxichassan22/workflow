"""Test: force reimport and clear cache."""
from dotenv import load_dotenv
load_dotenv()

import importlib
import maps_service
importlib.reload(maps_service)

from maps_service import (
    geocode_address, get_static_map, _draw_site_highlight,
    _overlay_markers, _build_markers, _apply_sepia_tone,
    _apply_map_overlay, SATELLITE_WITH_LABELS_STYLES, _osm_polygon_cache,
    _fetch_osm_polygon
)

# Clear cache
_osm_polygon_cache.clear()

lat, lng = 30.1194978, 31.3472959

# Test OSM fetch directly
print("Testing _fetch_osm_polygon directly...")
poly = _fetch_osm_polygon(lat, lng, radius_m=300)
if poly:
    print(f"Got polygon with {len(poly)} points")
    # Print bounding box
    lats = [p[0] for p in poly]
    lngs = [p[1] for p in poly]
    print(f"  Lat range: {min(lats):.6f} to {max(lats):.6f}")
    print(f"  Lng range: {min(lngs):.6f} to {max(lngs):.6f}")
else:
    print("No polygon found!")

# Generate map
out_path = "d:/workflow/test_highlight_cairo.png"
print("\nGenerating map...")
res = get_static_map(lat, lng, zoom=15, size=(1280, 720),
                     output_path=out_path, maptype="satellite",
                     styles=SATELLITE_WITH_LABELS_STYLES)

if res.get("success"):
    _apply_sepia_tone(out_path, intensity=0.35)
    _apply_map_overlay(out_path, dark_factor=0.12)
    
    # Clear cache again before highlight
    _osm_polygon_cache.clear()
    
    print("\nDrawing highlight...")
    hl = _draw_site_highlight(out_path, lat, lng, 15, size=(1280, 720))
    print(f"Highlight result: {hl}")
    
    markers = _build_markers(lat, lng)
    _overlay_markers(out_path, lat, lng, 15, markers, size=(1280, 720))
    print(f"\nDone! -> {out_path}")

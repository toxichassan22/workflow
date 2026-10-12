import base64
import io
import math
from decimal import Decimal, ROUND_HALF_UP

from PIL import Image, ImageColor, ImageDraw, ImageFont

from visual_plan_geometry import (edge_direction, fit_projection, isometric_projection,
                                  parcel_edges, segments, signed_area)
from visual_plan_scene import entry_position


COLORS = {'residential': '#B9D1EB', 'hotel': '#F5E5AB', 'retail': '#B6DED8',
          'office': '#E7C4D3', 'amenity': '#E7C4D3', 'service': '#D2D7DE',
          'parking': '#D2D7DE', 'landscape': '#D9E8D2'}
USE_LABELS = {'residential': 'Residential', 'hotel': 'Hotel', 'retail': 'Retail & F&B',
              'office': 'Offices', 'amenity': 'Amenities', 'service': 'Services',
              'parking': 'Parking', 'landscape': 'Open space'}
NAVY = '#172B4D'
WIDTH, HEIGHT = 1600, 900


def font(size):
    for name in ('DejaVuSans.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def figure(value):
    if value is None:
        return ''
    value = Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return format(value, ',f').removesuffix('.0')


def shade(color, factor):
    return tuple(max(0, min(255, round(channel * factor))) for channel in ImageColor.getrgb(color))


def label(draw, position, value, size=20, anchor=None, fill=NAVY):
    draw.text(position, str(value), fill=fill, font=font(size), anchor=anchor)


def polygon_center(polygon):
    area = signed_area(polygon)
    if not area:
        return (sum(point[0] for point in polygon) / len(polygon), sum(point[1] for point in polygon) / len(polygon))
    x = sum((a[0] + b[0]) * (a[0] * b[1] - b[0] * a[1]) for a, b in segments(polygon)) / (6 * area)
    y = sum((a[1] + b[1]) * (a[0] * b[1] - b[0] * a[1]) for a, b in segments(polygon)) / (6 * area)
    return x, y


def outlined(draw, polygon, fill, width=3):
    points = list(polygon)
    draw.polygon(points, fill=fill)
    draw.line(points + points[:1], fill=NAVY, width=width, joint='curve')


def legend(draw, scene):
    categories = list(dict.fromkeys(band['category'] for building in scene['buildings']
                                   for band in building['bands']))
    categories += [item['category'] for item in scene['siteItems'] if item['category'] not in categories]
    x, y = 45, HEIGHT - 104
    for category in categories:
        name = USE_LABELS.get(category, 'Amenities')
        width = draw.textlength(name, font=font(18)) + 62
        if x + width > WIDTH - 45:
            y -= 32
            x = 45
        draw.rectangle((x, y, x + 23, y + 18), fill=COLORS.get(category, COLORS['amenity']), outline=NAVY)
        label(draw, (x + 32, y - 2), name, 18)
        x += width


def frame(draw, kind, scene):
    title = {'site': 'CONCEPTUAL SITE PLAN', 'uses': 'VERTICAL PROGRAM DISTRIBUTION',
             'massing': 'CONCEPTUAL MASSING'}[kind]
    label(draw, (45, 28), title, 30)
    frontage = scene['primaryFrontage']['direction'].title()
    label(draw, (WIDTH - 45, 38), 'Primary frontage: ' + frontage, 21, 'ra')
    legend(draw, scene)
    label(draw, (WIDTH - 45, HEIGHT - 34), 'ILLUSTRATIVE REFERENCE - NOT TO SCALE', 18, 'ra')


def site_view(image, scene):
    draw = ImageDraw.Draw(image)
    polygons = [parcel['polygon'] for parcel in scene['geometry']['parcels']]
    project = fit_projection([point for polygon in polygons for point in polygon], WIDTH - 100, HEIGHT - 170, 110)
    screen = lambda point: (project(point)[0] + 50, project(point)[1] + 85)
    ground = Image.new('L', image.size, 0)
    mask_draw = ImageDraw.Draw(ground)
    for polygon in polygons:
        outlined(draw, [screen(point) for point in polygon], '#EDF3E8', 5)
        mask_draw.polygon([screen(point) for point in polygon], fill=255)
    guides = Image.new('RGB', image.size, 'white')
    guide_draw = ImageDraw.Draw(guides)
    guide_mask = Image.new('L', image.size, 0)
    line_mask = ImageDraw.Draw(guide_mask)
    for edge in parcel_edges(scene['geometry']):
        setback = scene['setbacks'].get(edge['direction'])
        if not setback:
            continue
        a, b = edge['a'], edge['b']
        parcel = next(item['polygon'] for item in scene['geometry']['parcels'] if item['id'] == edge['parcelId'])
        direction = 1 if signed_area(parcel) > 0 else -1
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        delta = (-direction * (b[1] - a[1]) * setback / length,
                 direction * (b[0] - a[0]) * setback / length)
        start, end = screen([a[0] + delta[0], a[1] + delta[1]]), screen([b[0] + delta[0], b[1] + delta[1]])
        line_length = math.dist(start, end)
        for offset in range(0, max(1, int(line_length)), 18):
            lo, hi = offset / max(line_length, 1), min(offset + 10, line_length) / max(line_length, 1)
            segment = [(start[0] + (end[0] - start[0]) * value, start[1] + (end[1] - start[1]) * value) for value in (lo, hi)]
            guide_draw.line(segment, fill='#81939F', width=2)
            line_mask.line(segment, fill=255, width=2)
    from PIL import ImageChops
    image.paste(guides, (0, 0), ImageChops.multiply(ground, guide_mask))
    draw = ImageDraw.Draw(image)
    for area in scene['openAreas']:
        color = COLORS['parking' if area['kind'] == 'surface_parking' else 'landscape']
        outlined(draw, [screen(point) for point in area['polygon']], color, 2)
        label(draw, screen(polygon_center(area['polygon'])), 'Surface Parking' if area['kind'] == 'surface_parking' else 'Landscape', 17, 'mm')
    for building in scene['buildings']:
        above = [band for band in building['bands'] if band['kind'] not in ('basement', 'roof')]
        category = above[0]['category'] if above else 'amenity'
        outlined(draw, [screen(point) for point in building['footprint']], COLORS.get(category, COLORS['amenity']), 4)
        center = screen(polygon_center(building['footprint']))
        label(draw, (center[0], center[1] - 10), building['label'], 19, 'mm')
        label(draw, (center[0], center[1] + 15), figure(building['footprintArea']) + ' m2', 16, 'mm')
    for entry in scene['entries']:
        point = screen(entry_position(entry, scene))
        draw.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill=NAVY)
        label(draw, (point[0] + 12, point[1] - 16), entry['kind'].title() + ' Entry', 17)
    for edge in parcel_edges(scene['geometry']):
        a, b = edge['a'], edge['b']
        position = screen([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
        direction = edge['direction']
        row = next((item for item in scene['directions'] if item['direction'] == direction), {})
        title = direction.title() + (' Street' if row.get('street') else ' Edge')
        if row.get('streetWidth') is not None:
            title += ' ' + figure(row['streetWidth']) + ' m'
        label(draw, (position[0], position[1] - 20), title, 16, 'mm')
    label(draw, (WIDTH - 100, 100), 'N', 25)


def facade_texture(image, polygon, style):
    if not style or (style.get('material', 'neutral') == 'neutral' and style.get('pattern', 'plain') == 'plain'):
        return
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    layer = Image.new('RGB', image.size, 'white')
    draw = ImageDraw.Draw(layer)
    pattern = style.get('pattern') or ('grid' if style.get('material') == 'glass' else 'horizontal')
    min_x, max_x = int(min(point[0] for point in polygon)), int(max(point[0] for point in polygon))
    min_y, max_y = int(min(point[1] for point in polygon)), int(max(point[1] for point in polygon))
    line_mask = Image.new('L', image.size, 0)
    lines = ImageDraw.Draw(line_mask)
    if pattern in ('vertical', 'grid'):
        for x in range(min_x, max_x + 1, 24):
            draw.line((x, min_y, x, max_y), fill='#7C98AB', width=2)
            lines.line((x, min_y, x, max_y), fill=255, width=2)
    if pattern in ('horizontal', 'grid'):
        for y in range(min_y, max_y + 1, 22):
            draw.line((min_x, y, max_x, y), fill='#7C98AB', width=2)
            lines.line((min_x, y, max_x, y), fill=255, width=2)
    from PIL import ImageChops
    image.paste(layer, (0, 0), ImageChops.multiply(mask, line_mask))


def massing_view(image, scene):
    draw = ImageDraw.Draw(image)
    frontage = scene['primaryFrontage']['direction']
    ground = [point for parcel in scene['geometry']['parcels'] for point in parcel['polygon']]
    span = max(max(point[0] for point in ground) - min(point[0] for point in ground),
               max(point[1] for point in ground) - min(point[1] for point in ground))
    step = span / 20
    highest = max((building['levels'] for building in scene['buildings']), default=0) * step
    projected = [isometric_projection(point, z, frontage)[:2] for point in ground for z in (0, highest)]
    fit = fit_projection(projected, WIDTH - 100, HEIGHT - 170, 110)
    screen = lambda point, z=0: (fit(isometric_projection(point, z, frontage)[:2])[0] + 50,
                                  fit(isometric_projection(point, z, frontage)[:2])[1] + 85)
    for parcel in scene['geometry']['parcels']:
        outlined(draw, [screen(point) for point in parcel['polygon']], '#EDF3E8', 5)
    for area in scene['openAreas']:
        outlined(draw, [screen(point) for point in area['polygon']],
                 COLORS['parking' if area['kind'] == 'surface_parking' else 'landscape'], 2)
    ordered = sorted(scene['buildings'], key=lambda item: isometric_projection(polygon_center(item['footprint']), 0, frontage)[2])
    for building in ordered:
        polygon = building['footprint']
        bands = [band for band in building['bands'] if band['kind'] != 'basement']
        for band in sorted(bands, key=lambda item: (item['start'], item['end'])):
            bottom, top = band['start'] * step, band['end'] * step
            category = band['category']
            base_color = COLORS.get(category, COLORS['amenity'])
            for a, b in segments(polygon):
                direction = edge_direction(a, b, polygon)
                normal = {'north': (0, 1), 'south': (0, -1), 'east': (1, 0), 'west': (-1, 0)}[direction]
                if isometric_projection(normal, 0, frontage)[2] <= 0:
                    continue
                style = building['facades'].get(direction, {})
                color = style.get('color') or base_color
                face = [screen(a, bottom), screen(b, bottom), screen(b, top), screen(a, top)]
                outlined(draw, face, shade(color, 0.92 if direction == frontage else 0.78), 2)
                facade_texture(image, face, style)
                draw = ImageDraw.Draw(image)
                floors = max(1, math.ceil(band['end'] - band['start']))
                for floor in range(1, min(floors, 80)):
                    z = bottom + (top - bottom) * floor / floors
                    draw.line([screen(a, z), screen(b, z)], fill='white', width=1)
            outlined(draw, [screen(point, top) for point in polygon], base_color, 2)
        center = screen(polygon_center(polygon), building['levels'] * step)
        label(draw, (center[0], center[1] - 18), building['label'], 18, 'mm')
    for entry in scene['entries']:
        point = screen(entry_position(entry, scene))
        draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill=NAVY)
        label(draw, (point[0] + 10, point[1] - 16), entry['kind'].title() + ' Entry', 16)
    label(draw, (45, HEIGHT - 140), 'Floor heights are schematic; surveyed parcel geometry is fixed.', 17)


def uses_view(image, scene):
    draw = ImageDraw.Draw(image)
    buildings = scene['buildings']
    if not buildings:
        label(draw, (WIDTH / 2, HEIGHT / 2), 'No above-ground buildings recorded', 24, 'mm')
        return
    column = (WIDTH - 120) / len(buildings)
    low = min((band['start'] for building in buildings for band in building['bands']), default=0)
    high = max((band['end'] for building in buildings for band in building['bands']), default=1)
    scale = 550 / max(high - low, 1)
    for index, building in enumerate(buildings):
        x0, x1 = 60 + index * column + 12, 60 + (index + 1) * column - 12
        label(draw, ((x0 + x1) / 2, 120), building['label'], 21, 'mm')
        bands = sorted(building['bands'], key=lambda item: (item['start'], item['end']))
        for band in bands:
            y0 = 700 - (band['end'] - low) * scale
            y1 = 700 - (band['start'] - low) * scale
            shared = [item for item in bands if item['start'] == band['start'] and item['end'] == band['end']]
            position = shared.index(band)
            width = (x1 - x0) / len(shared)
            left, right = x0 + position * width, x0 + (position + 1) * width
            draw.rectangle((left, y0, right, y1), fill=COLORS.get(band['category'], COLORS['amenity']), outline=NAVY, width=2)
            title = band['label'] + ' (' + band['floorLabel'] + ')'
            label(draw, ((left + right) / 2, (y0 + y1) / 2 - 10), title, 17, 'mm')
            values = [figure(band['area']) + ' m2' if band['area'] is not None else '',
                      figure(band['units']) + ' units/floor' if band['units'] is not None else '']
            label(draw, ((left + right) / 2, (y0 + y1) / 2 + 14), ' / '.join(value for value in values if value), 15, 'mm')
        ground_y = 700 - (0 - low) * scale
        draw.line((x0, ground_y, x1, ground_y), fill=NAVY, width=4)
        label(draw, (x0, ground_y + 4), 'Ground Level', 15)


def render_plan(scene, kind):
    if kind not in ('site', 'uses', 'massing'):
        raise ValueError('Unknown plan kind')
    image = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    {'site': site_view, 'uses': uses_view, 'massing': massing_view}[kind](image, scene)
    frame(ImageDraw.Draw(image), kind, scene)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')

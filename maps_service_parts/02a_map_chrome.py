def _draw_catchment_zones(image_path, center_lat, center_lng, zoom, zones, scale=2,
                          site_lat=None, site_lng=None):
    """Draw smooth, anti-aliased concentric catchment rings and elegant label pills using PIL."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        cx, cy = img_w // 2, img_h // 2
        
        # Create a high-res canvas for anti-aliasing
        canvas_scale = 4
        canvas_w = img_w * canvas_scale
        canvas_h = img_h * canvas_scale
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        
        ccx = canvas_w // 2
        ccy = canvas_h // 2
        # The rings belong to the site, not to the viewport centre — a manually
        # panned frame shifts the image centre while the circles stay on the plot.
        ring_anchor_lat, ring_anchor_lng = center_lat, center_lng
        if site_lat is not None and site_lng is not None:
            ring_anchor_lat, ring_anchor_lng = site_lat, site_lng
            site_dx, site_dy = _latlng_to_pixel_offset(site_lat, site_lng, center_lat, center_lng, zoom, scale=scale)
            ccx = int(round(canvas_w / 2 + site_dx * canvas_scale))
            ccy = int(round(canvas_h / 2 + site_dy * canvas_scale))
        
        # Theme colors: Gold/Maroon/Teal for premium look
        # [Inner, Middle, Outer]
        fill_colors = [
            (107, 28, 35, 20),   # Subtle dark maroon fill (alpha 20)
            (171, 131, 75, 15),  # Subtle bronze/gold fill (alpha 15)
            (37, 75, 102, 12),   # Subtle dark blue/teal fill (alpha 12)
        ]
        border_colors = [
            (107, 28, 35, 160),  # Dark maroon
            (171, 131, 75, 150), # Bronze/gold
            (37, 75, 102, 130),  # Teal/blue
        ]
        
        # Sort zones from largest radius to smallest, so smaller ones are drawn on top
        sorted_zones = sorted(zones, key=lambda z: z.get('km', z.get('minutes', 5) * 0.8), reverse=True)
        
        for idx, zone in enumerate(sorted_zones):
            radius_km = zone.get('km', zone.get('minutes', 5) * 0.8 / 1.60934)
            radius_m = radius_km * 1000.0
            
            # Get latitude offset for radius — measured at the ring anchor (the
            # site), not the frame centre, so a panned frame keeps true metres.
            lat_offset = radius_m / 111320.0
            _, dy = _latlng_to_pixel_offset(ring_anchor_lat + lat_offset, ring_anchor_lng, ring_anchor_lat, ring_anchor_lng, zoom, scale=scale)
            
            # Scale to canvas coordinates
            r = int(abs(dy) * canvas_scale)
            
            color_idx = idx % len(fill_colors)
            fill_c = fill_colors[color_idx]
            border_c = border_colors[color_idx]
            
            # Draw catchment circle
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=fill_c, outline=border_c, width=3 * canvas_scale)
            # Add thin white inner edge for premium glassmorphism glow
            draw.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=None, outline=(255, 255, 255, 60), width=1 * canvas_scale)
            
            # Draw elegant label pill for each zone
            label = zone.get('label') or f"{zone.get('minutes', 5)} دقائق"
            font = _get_arabic_font(14 * canvas_scale)
            reshaped = _reshape_arabic_text(label)
                
            bbox = draw.textbbox((0, 0), reshaped, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            # Spread the pills around the circle: stacking them all straight above the centre
            # buried the innermost label under the site pin.
            pad_x = 10 * canvas_scale
            pad_y = 5 * canvas_scale
            angle = math.radians(90 + 35 * (idx % 3))
            lx = int(ccx + r * math.cos(angle))
            ly = int(ccy - r * math.sin(angle))
            
            label_width = tw + pad_x * 2
            label_height = th + pad_y * 2
            rect_left = max(8 * canvas_scale, min(canvas_w - label_width - 8 * canvas_scale, lx - label_width // 2))
            rect_top = max(8 * canvas_scale, min(canvas_h - label_height - 8 * canvas_scale, ly - label_height // 2))
            rect = [rect_left, rect_top, rect_left + label_width, rect_top + label_height]

            # Draw pill background and border
            draw.rounded_rectangle(rect, radius=4 * canvas_scale, fill=border_c, outline=(255, 255, 255, 200), width=1 * canvas_scale)
            draw.text((rect_left + pad_x - bbox[0], rect_top + pad_y - bbox[1]), reshaped, fill='#FFFFFF', font=font)

        # Downsample with LANCZOS
        resized = canvas.resize((img_w, img_h), Image.Resampling.LANCZOS)
        img = Image.alpha_composite(img, resized)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[DRAW CATCHMENT ERROR] {e}")
        return False


def _post_process_streetview(image_path, heading, index):
    """Apply professional enhancements to Street View images: vignette, contrast, elegant borders, and direction labels."""
    try:
        from PIL import ImageEnhance
        img = Image.open(image_path).convert('RGBA')
        w, h = img.size
        
        # 1. Enhance Contrast & Color Saturation slightly for a professional architectural photo look
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.15)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.05)
        
        # 2. Add subtle warm sepia-like color balance
        r, g, b, a = img.split()
        grey = img.convert('L')
        # Warm golden-cream tint
        sepia_r = grey.point(lambda x: min(255, int(x * 1.05)))
        sepia_g = grey.point(lambda x: min(255, int(x * 1.00)))
        sepia_b = grey.point(lambda x: min(255, int(x * 0.92)))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        img = Image.blend(img, sepia, 0.15) # Subtle blending
        
        # 3. Create a professional vignette (darkening towards corners)
        vignette = Image.new('L', (w, h), 255)
        v_draw = ImageDraw.Draw(vignette)
        # Draw a radial gradient centered
        for i in range(min(w, h) // 2):
            alpha = int(120 * (i / (min(w, h) // 2)) ** 2) # quadratic scaling for smooth transition
            v_draw.ellipse([i, i, w - i, h - i], outline=255 - alpha)
        
        # Apply vignette as alpha mask on black overlay
        black_overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        for x in range(w):
            for y in range(h):
                val = vignette.getpixel((x, y))
                if val < 255:
                    black_overlay.putpixel((x, y), (0, 0, 0, int((255 - val) * 0.4)))
        img = Image.alpha_composite(img, black_overlay)
        
        # 4. Draw elegant thin gold/cream border and white inner frame
        draw = ImageDraw.Draw(img)
        border_w = 4
        # Outer gold/bronze border
        gold_color = (171, 131, 75, 230)
        draw.rectangle([0, 0, w - 1, h - 1], outline=gold_color, width=border_w)
        # Inner thin white line
        draw.rectangle([border_w + 2, border_w + 2, w - border_w - 3, h - border_w - 3], outline=(255, 255, 255, 120), width=1)
        
        # 5. Add an elegant direction label pill at the bottom-right
        directions = {
            0: "إطلالة الشمال",
            90: "إطلالة الشرق",
            180: "إطلالة الجنوب",
            270: "إطلالة الغرب"
        }
        dir_text = directions.get(heading, f"إطلالة {heading} درجة")
        font = _get_arabic_font(14)
        reshaped = _reshape_arabic_text(dir_text)
            
        bbox = draw.textbbox((0, 0), reshaped, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        
        pad_x = 12
        pad_y = 6
        rx = w - border_w - 15 - tw - pad_x * 2
        ry = h - border_w - 15 - th - pad_y * 2
        
        rect = [rx, ry, w - border_w - 15, h - border_w - 15]
        
        # Dark transculent background for label
        draw.rounded_rectangle(rect, radius=5, fill=(37, 75, 102, 210), outline=gold_color, width=1)
        draw.text((rx + pad_x, ry + pad_y - 2), reshaped, fill='#FFFFFF', font=font)
        
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[STREETVIEW ENHANCE ERROR] {e}")
        return False


def _draw_compass(image_path, position='top-right', compass_size=60, language='ar'):
    """Draw a professional compass indicator (ش / N = North) matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        img_w, img_h = img.size
        overlay = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Position compass
        margin = 30
        if position == 'top-right':
            comp_cx = img_w - margin - compass_size // 2
            comp_cy = margin + compass_size // 2
        else:
            comp_cx = margin + compass_size // 2
            comp_cy = margin + compass_size // 2

        r = compass_size // 2
        # Outer circle (cream/beige)
        draw.ellipse([comp_cx - r, comp_cy - r, comp_cx + r, comp_cy + r],
                     fill=(240, 230, 210, 220), outline=COMPASS_COLOR + (255,), width=3)

        font = _get_arabic_font(compass_size // 2)
        text = _reshape_arabic_text('N' if _lang_norm(language) == 'en' else 'ش')
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((comp_cx - tw // 2, comp_cy - th // 2 - 2), text,
                  fill=COMPASS_COLOR + (255,), font=font)

        # Small triangle pointing up (North indicator)
        tri_size = 8
        draw.polygon([(comp_cx, comp_cy - r + 6),
                      (comp_cx - tri_size // 2, comp_cy - r + 6 + tri_size),
                      (comp_cx + tri_size // 2, comp_cy - r + 6 + tri_size)],
                     fill=COMPASS_COLOR + (255,))

        img = Image.alpha_composite(img, overlay)
        img.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[COMPASS ERROR] {e}")
        return False


def _apply_sepia_tone(image_path, intensity=0.3):
    """Apply a warm sepia tone to satellite imagery matching reference examples."""
    try:
        img = Image.open(image_path).convert('RGBA')
        r, g, b, a = img.split()
        # Convert to greyscale
        grey = img.convert('L')
        # Create sepia channels (warm brown tone)
        sepia_r = grey.point(lambda x: min(255, int(x * (1 + 0.2 * intensity))))
        sepia_g = grey.point(lambda x: min(255, int(x * (1 + 0.05 * intensity))))
        sepia_b = grey.point(lambda x: min(255, int(x * (1 - 0.1 * intensity))))
        sepia = Image.merge('RGBA', (sepia_r, sepia_g, sepia_b, a))
        # Blend original with sepia
        result = Image.blend(img, sepia, intensity)
        result.save(image_path, 'PNG')
        return True
    except Exception as e:
        print(f"[SEPIA ERROR] {e}")
        return False


def _draw_inset_map(image_path, center_lat, center_lng, inset_size=180, language='ar'):
    """Draw a small inset/overview map in the bottom-right corner."""
    try:
        # Download a smaller wide-area map
        inset_path = image_path + '.inset.png'
        inset_res = get_static_map(center_lat, center_lng, zoom=9,
                                    size=(inset_size, inset_size),
                                    output_path=inset_path,
                                    styles=SATELLITE_CLEAN_STYLES,
                                    language=language)
        if not inset_res.get('success'):
            return False

        img = Image.open(image_path).convert('RGBA')
        inset = Image.open(inset_path).convert('RGBA')
        # Resize inset (scale=2 makes it 2x, resize down)
        inset = inset.resize((inset_size, inset_size), Image.LANCZOS)

        img_w, img_h = img.size
        # Position: bottom-right with margin
        margin = 20
        ix = img_w - inset_size - margin
        iy = img_h - inset_size - margin

        # Draw border around inset
        border = Image.new('RGBA', (inset_size + 6, inset_size + 6), (240, 230, 210, 200))
        img.paste(border, (ix - 3, iy - 3), border)
        img.paste(inset, (ix, iy), inset)

        # Draw site marker on inset (center dot)
        draw = ImageDraw.Draw(img)
        inset_cx = ix + inset_size // 2
        inset_cy = iy + inset_size // 2
        # Small maroon triangle pin
        pin_s = 10
        draw.polygon([(inset_cx - pin_s, inset_cy - pin_s // 2),
                      (inset_cx + pin_s, inset_cy - pin_s // 2),
                      (inset_cx, inset_cy + pin_s)],
                     fill=MARKER_COLOR_SITE)

        img.save(image_path, 'PNG')

        # Cleanup temp inset file
        try:
            os.remove(inset_path)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[INSET MAP ERROR] {e}")
        return False



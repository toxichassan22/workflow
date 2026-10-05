STATIC_MAP_FRAME_VERSION = 2


def _map_viewport_size(value):
    if not isinstance(value, dict):
        return None
    try:
        width, height = int(value.get('width')), int(value.get('height'))
    except (TypeError, ValueError, OverflowError):
        return None
    return (width, height) if 64 <= width <= 2048 and 64 <= height <= 2048 else None


def _stored_map_viewport_size(metadata):
    return _map_viewport_size(metadata.get('viewport_size')) or (1280, 720)


def _map_size_metadata(size):
    return {'width': size[0], 'height': size[1]}


def _map_frame_center(lat, lng, size):
    return {'lat': lat, 'lng': lng, **_map_size_metadata(size)}


def _stored_map_frame_center(lat, lng, metadata):
    size = _map_viewport_size(metadata.get('viewport_size'))
    return _map_frame_center(lat, lng, size) if size else {'lat': lat, 'lng': lng}


def _prepare_static_map_image(path, provider_size, factor, size):
    try:
        with Image.open(path) as source:
            if source.size != (provider_size[0] * 2, provider_size[1] * 2):
                return False
            if factor == 1:
                return True
            image = source.resize((source.width * factor, source.height * factor), Image.Resampling.LANCZOS)
        width, height = size[0] * 2, size[1] * 2
        left, top = (image.width - width) // 2, (image.height - height) // 2
        image.crop((left, top, left + width, top + height)).save(path, 'PNG')
        return True
    except (OSError, ValueError):
        return False


def _static_map_image_matches(path, size):
    try:
        with Image.open(path) as image:
            return image.size == (size[0] * 2, size[1] * 2)
    except (OSError, ValueError):
        return False

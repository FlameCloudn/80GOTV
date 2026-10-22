"""队标的统一处理：上传时自动去掉纯色背景、裁掉空白、居中放进正方形画布，
并把数据库里各种写法的队标路径统一换算成图片地址。

处理规则（只依赖 Pillow）：
1. 图片本身已经有透明背景 → 不动背景，只裁边、居中。
2. 四周边缘几乎是同一种颜色（白底、黑底、任意纯色底）→ 把“从边缘连过来的这种颜色”变透明；
   被图案包在里面的同色区域（比如 U8 标志中间的白色 8）保留。
3. 浅色背景上：挨着背景、颜色很淡、附近又没有鲜明图案的像素（网站水印、压缩噪点）一起去掉。
4. 背景边缘往里几圈做半透明过渡，并还原被背景色“染过”的颜色，避免白边/黑边。
5. 边缘颜色杂（照片、渐变背景）→ 认为没有纯色背景，背景不动。
6. 去掉贴着图片边缘、离主体很远的小碎块。
7. 最后裁掉四周透明空白，居中放进正方形画布（四周留 8% 边距），统一输出 256×256 PNG。
"""

import os
import uuid
from collections import deque

from flask import url_for
from PIL import Image, ImageOps, UnidentifiedImageError

# 处理后队标的统一规格
TEAM_LOGO_DIR = "team_logos"  # static/uploads/ 下面的子目录
TEAM_LOGO_SIZE = 256  # 输出画布边长
TEAM_LOGO_MARGIN = 0.08  # 画布四周留白占边长的比例
WORKING_MAX_SIDE = 512  # 处理前先把大图缩到这个尺寸以内，避免上传大图时处理太慢

# 判断“纯色背景”的参数
_BORDER_UNIFORM_RATIO = 0.82  # 边缘至少这么多像素接近同一种颜色，才认为是纯色背景
_BORDER_MATCH_DISTANCE = 42  # 边缘像素和背景色的距离在这以内算“接近”
_ALPHA_VISIBLE = 12  # 透明度高于这个值才算看得见的像素
_FRINGE_WIDTH = 3  # 背景边缘往里几圈做半透明过渡（缩小过的图，锯齿过渡往往有 2~3 像素宽）
_FAINT_DISTANCE = 60  # 和背景色距离小于这个值的像素算“很淡”（网站水印、压缩噪点通常是这样）
_STRONG_DISTANCE = 120  # 和背景色距离不小于这个值的像素算“鲜明图案”
_STRONG_RADIUS = 3  # 很淡的像素周围这么多像素内有鲜明图案，就当作图案的边缘，不去掉
_LIGHT_BACKGROUND = 200  # 背景平均亮度不低于这个值，才做“去淡色水印”


def _working_copy(source):
    """取第一帧、按照片方向转正、转成 RGBA，并限制处理尺寸。"""
    if getattr(source, "is_animated", False):
        source.seek(0)
    source.load()
    image = ImageOps.exif_transpose(source).convert("RGBA")
    image.thumbnail((WORKING_MAX_SIDE, WORKING_MAX_SIDE), Image.Resampling.LANCZOS)
    return image


def _pixel_list(image):
    """按行展开的像素列表（Pillow 新版本用 get_flattened_data，旧版本用 getdata）。"""
    getter = getattr(image, "get_flattened_data", None)
    return list(getter() if getter else image.getdata())


def _border_indexes(width, height):
    """图片最外一圈像素的位置（按行展开后的下标）。"""
    indexes = set()
    for x in range(width):
        indexes.add(x)
        indexes.add((height - 1) * width + x)
    for y in range(height):
        indexes.add(y * width)
        indexes.add(y * width + width - 1)
    return sorted(indexes)


def _neighbours(index, width, total):
    """上下左右四个相邻像素的位置（越界的不算）。"""
    x = index % width
    if index >= width:
        yield index - width
    if index + width < total:
        yield index + width
    if x > 0:
        yield index - 1
    if x < width - 1:
        yield index + 1


def _distance(pixel, color):
    """两个颜色在 RGB 空间里的直线距离。"""
    return (
        (pixel[0] - color[0]) ** 2 + (pixel[1] - color[1]) ** 2 + (pixel[2] - color[2]) ** 2
    ) ** 0.5


def _has_transparent_background(pixels, border):
    """边缘大部分已经是透明的，说明上传的是透明底队标。"""
    clear = sum(1 for index in border if pixels[index][3] < 200)
    return clear >= len(border) * 0.5


def _detect_background(pixels, border):
    """边缘颜色足够统一时返回 (背景色, 边缘噪声大小)，否则返回 (None, 0)。"""
    colors = [pixels[index][:3] for index in border]
    middle = len(colors) // 2
    background = tuple(sorted(color[channel] for color in colors)[middle] for channel in range(3))
    close = sorted(
        value
        for value in (_distance(pixels[index], background) for index in border)
        if value <= _BORDER_MATCH_DISTANCE
    )
    if len(close) < len(border) * _BORDER_UNIFORM_RATIO:
        return None, 0.0
    noise = close[int(len(close) * 0.95) - 1] if close else 0.0
    return background, noise


def _flood_background(distances, width, height, start, limit, allowed=None):
    """从 start 标记的背景出发，把和背景色距离在 limit 以内、连在一起的像素也标成背景
    （上下左右四个方向连通）。allowed 不为空时，只能扩展到 allowed 标记过的像素。"""
    total = width * height
    is_background = bytearray(start)
    queue = deque(index for index in range(total) if is_background[index])
    while queue:
        index = queue.popleft()
        for neighbour in _neighbours(index, width, total):
            if is_background[neighbour] or distances[neighbour] > limit:
                continue
            if allowed is not None and not allowed[neighbour]:
                continue
            is_background[neighbour] = 1
            queue.append(neighbour)
    return is_background


def _window_hits(marks, length, stride, count, radius):
    """沿一个方向判断每个位置前后 radius 内有没有标记（用前缀和，速度和 radius 无关）。"""
    hits = bytearray(len(marks))
    for line in range(count):
        base = line * (1 if stride != 1 else length)
        prefix = [0]
        for step in range(length):
            prefix.append(prefix[-1] + marks[base + step * stride])
        for step in range(length):
            if prefix[min(length, step + radius + 1)] - prefix[max(0, step - radius)]:
                hits[base + step * stride] = 1
    return hits


def _far_from_strong(distances, width, height):
    """标出周围 _STRONG_RADIUS 像素内都没有“鲜明图案”的像素。"""
    strong = bytearray(1 if value >= _STRONG_DISTANCE else 0 for value in distances)
    across = _window_hits(strong, width, 1, height, _STRONG_RADIUS)
    near = _window_hits(across, height, width, width, _STRONG_RADIUS)
    return bytearray(0 if value else 1 for value in near)


def _fringe_rings(is_background, width, height):
    """离背景区域 1、2、3 个像素远的像素，按圈返回。"""
    total = width * height
    taken = bytearray(is_background)
    ring = [
        index
        for index in range(total)
        if not taken[index] and any(is_background[n] for n in _neighbours(index, width, total))
    ]
    rings = []
    while ring and len(rings) < _FRINGE_WIDTH:
        for index in ring:
            taken[index] = 1
        rings.append(ring)
        ring = list({n for index in ring for n in _neighbours(index, width, total) if not taken[n]})
    return rings


def _foreground_reference(distances, is_background, index, width, height):
    """在周围 5×5 范围里找离背景色最远的像素，用它的距离当作“这一处图案本来的浓度”。"""
    x, y = index % width, index // width
    best = distances[index]
    for ny in range(max(0, y - 2), min(height, y + 3)):
        for nx in range(max(0, x - 2), min(width, x + 3)):
            neighbour = ny * width + nx
            if not is_background[neighbour] and distances[neighbour] > best:
                best = distances[neighbour]
    return best


def _unmix(pixel, background, alpha):
    """去掉混进边缘像素里的背景色：已知透明度，反推出图案本来的颜色。"""
    channels = []
    for channel in range(3):
        value = (pixel[channel] - (1 - alpha) * background[channel]) / alpha
        channels.append(int(min(255, max(0, round(value)))))
    return (channels[0], channels[1], channels[2], int(round(pixel[3] * alpha)))


def _remove_background(pixels, width, height, border, background, noise):
    """把纯色背景变透明，返回 (新的像素列表, 每个像素和背景色的距离)。"""
    hard = min(70.0, max(20.0, noise * 1.6 + 8))
    distances = [_distance(pixel, background) for pixel in pixels]
    seeds = bytearray(width * height)
    for index in border:
        if distances[index] <= hard:
            seeds[index] = 1
    is_background = _flood_background(distances, width, height, seeds, hard)
    # 去淡色水印只用在浅色背景上：深色背景的队标里，暗色纹理往往就是图案本身
    if sum(background) / 3 >= _LIGHT_BACKGROUND:
        lonely = _far_from_strong(distances, width, height)
        is_background = _flood_background(
            distances, width, height, is_background, _FAINT_DISTANCE, allowed=lonely
        )
    result = [(0, 0, 0, 0) if is_background[i] else pixel for i, pixel in enumerate(pixels)]
    for ring in _fringe_rings(is_background, width, height):
        for index in ring:
            reference = _foreground_reference(distances, is_background, index, width, height)
            if reference <= hard:
                continue
            alpha = min(1.0, distances[index] / reference)
            if alpha < 0.03:
                result[index] = (0, 0, 0, 0)
            elif alpha < 0.98:
                result[index] = _unmix(pixels[index], background, alpha)
    return result, distances


def _components(alpha, width, height):
    """把看得见的像素按“连在一起”分组，返回每组的像素下标列表（八个方向连通）。"""
    total = width * height
    seen = bytearray(total)
    groups = []
    for start in range(total):
        if seen[start] or alpha[start] <= _ALPHA_VISIBLE:
            continue
        seen[start] = 1
        group = [start]
        queue = deque([start])
        while queue:
            index = queue.popleft()
            x, y = index % width, index // width
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if (dx or dy) and 0 <= nx < width and 0 <= ny < height:
                        neighbour = ny * width + nx
                        if not seen[neighbour] and alpha[neighbour] > _ALPHA_VISIBLE:
                            seen[neighbour] = 1
                            group.append(neighbour)
                            queue.append(neighbour)
        groups.append(group)
    return groups


def _bounds(group, width):
    xs = [index % width for index in group]
    ys = [index // width for index in group]
    return min(xs), min(ys), max(xs), max(ys)


def _remove_edge_specks(pixels, distances, width, height):
    """去掉贴着图片边缘的小碎块：要么离主体很远，要么颜色淡得接近背景。
    主体附近、颜色鲜明的小部件一律保留。"""
    groups = _components([pixel[3] for pixel in pixels], width, height)
    if len(groups) < 2:
        return pixels
    groups.sort(key=len, reverse=True)
    main_left, main_top, main_right, main_bottom = _bounds(groups[0], width)
    total_visible = sum(len(group) for group in groups)
    band_x, band_y = width * 0.12, height * 0.12
    gap_x, gap_y = width * 0.03, height * 0.03
    result = list(pixels)
    for group in groups[1:]:
        if len(group) > total_visible * 0.015:
            continue
        left, top, right, bottom = _bounds(group, width)
        near_edge = (
            left < band_x or top < band_y or right > width - band_x or bottom > height - band_y
        )
        far_from_main = (
            right < main_left - gap_x
            or left > main_right + gap_x
            or bottom < main_top - gap_y
            or top > main_bottom + gap_y
        )
        faint = sum(distances[index] for index in group) / len(group) < 70
        if near_edge and (far_from_main or faint):
            for index in group:
                result[index] = (0, 0, 0, 0)
    return result


def _fit_square(image):
    """裁掉透明空白，先缩放到画布内的可用尺寸，再居中放进 TEAM_LOGO_SIZE 见方的画布。"""
    bbox = image.getchannel("A").point(lambda value: 255 if value > _ALPHA_VISIBLE else 0).getbbox()
    if bbox:
        image = image.crop(bbox)
    inner = round(TEAM_LOGO_SIZE * (1 - 2 * TEAM_LOGO_MARGIN))
    scale = inner / max(image.width, image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    # 先换成“预乘透明度”再缩放，透明区域的颜色才不会在边缘晕出一圈杂色
    logo = image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    # 缩放会在边缘外面留下几乎看不见的残影，直接清成全透明
    logo.putalpha(logo.getchannel("A").point(lambda value: 0 if value < 8 else value))
    canvas = Image.new("RGBA", (TEAM_LOGO_SIZE, TEAM_LOGO_SIZE), (0, 0, 0, 0))
    canvas.paste(logo, ((TEAM_LOGO_SIZE - size[0]) // 2, (TEAM_LOGO_SIZE - size[1]) // 2))
    return canvas


def process_logo_image(source):
    """把任意队标图片处理成统一规格：透明背景、去掉空白、居中、TEAM_LOGO_SIZE 见方。"""
    image = _working_copy(source)
    width, height = image.size
    pixels = _pixel_list(image)
    border = _border_indexes(width, height)
    if not _has_transparent_background(pixels, border):
        background, noise = _detect_background(pixels, border)
        if background is not None:
            cleaned, distances = _remove_background(
                pixels, width, height, border, background, noise
            )
            cleaned = _remove_edge_specks(cleaned, distances, width, height)
            # 去完背景几乎什么都不剩（比如上传的是一整块纯色图），说明判断不适用，保留原图
            visible = sum(1 for pixel in cleaned if pixel[3] > _ALPHA_VISIBLE)
            if visible >= width * height * 0.03:
                pixels = cleaned
    image = Image.new("RGBA", (width, height))
    image.putdata(pixels)
    return _fit_square(image)


# ── 保存 / 删除 ──────────────────────────────────────────


def _logo_dir(app_root_path):
    return os.path.join(app_root_path, "static", "uploads", TEAM_LOGO_DIR)


def _original_dir(app_root_path):
    """原图备份放在不对外公开的 instance 目录，以后算法改进了可以重新处理。"""
    return os.path.join(app_root_path, "instance", "team_logo_originals")


def original_logo_path(app_root_path, filename):
    """某个队标的原图备份位置。"""
    return os.path.join(_original_dir(app_root_path), filename)


def save_processed_logo(source, app_root_path, filename=None):
    """处理一张已经打开的图片并保存，返回保存的文件名（不含目录）。

    第一次保存时先把原图备份到 instance/team_logo_originals/（已有备份就不覆盖，
    这样重复处理旧队标时始终从真正的原图开始，不会对处理过的图再处理一遍）。
    """
    filename = filename or f"{uuid.uuid4().hex}.png"
    logo_dir = _logo_dir(app_root_path)
    os.makedirs(logo_dir, exist_ok=True)
    os.makedirs(_original_dir(app_root_path), exist_ok=True)
    original = _working_copy(source)
    backup_path = original_logo_path(app_root_path, filename)
    if not os.path.exists(backup_path):
        original.save(backup_path, format="PNG", optimize=True)
    processed = process_logo_image(original)
    temp_path = os.path.join(logo_dir, f".{filename}.{uuid.uuid4().hex}.tmp")
    try:
        processed.save(temp_path, format="PNG", optimize=True)
        os.replace(temp_path, os.path.join(logo_dir, filename))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return filename


def save_uploaded_logo_file(file, app_root_path):
    """处理上传的队标文件（调用方已检查过扩展名和文件内容）。失败返回 None。"""
    try:
        with Image.open(file.stream) as source:
            return save_processed_logo(source, app_root_path)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None
    finally:
        file.stream.seek(0)


def remove_logo_files(app_root_path, filename):
    """删除站内队标及其原图备份，只接受本站生成的纯文件名。"""
    if not filename or os.path.basename(filename) != filename:
        return
    for folder in (_logo_dir(app_root_path), _original_dir(app_root_path)):
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


# ── 路径与地址 ──────────────────────────────────────────


def logo_relative_path(value):
    """把数据库里各种写法的队标统一成 static/uploads/ 下的相对路径。

    teams.logo 存的是 “team_logos/xx.png”，报名表 event_registrations.team_logo 存的是 “xx.png”，
    个别旧数据带 “uploads/” 或 “/static/uploads/” 前缀。外部链接和其它站内绝对路径原样返回。
    """
    value = str(value or "").strip().replace("\\", "/")
    if not value or value.startswith(("http://", "https://")):
        return value
    for prefix in ("/static/uploads/", "static/uploads/", "/uploads/", "uploads/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    else:
        if value.startswith("/"):
            return value
    if "/" not in value:
        value = f"{TEAM_LOGO_DIR}/{value}"
    return value


def team_logo_url(value, app_root_path=None):
    """模板里统一用的队标地址；站内文件带上修改时间做版本号，重新处理后浏览器会拿到新图。"""
    path = logo_relative_path(value)
    if not path:
        return ""
    if path.startswith(("http://", "https://", "/")):
        return path
    url = url_for("static", filename=f"uploads/{path}")
    if app_root_path:
        full_path = os.path.join(app_root_path, "static", "uploads", *path.split("/"))
        if os.path.isfile(full_path):
            url = f"{url}?v={int(os.path.getmtime(full_path))}"
    return url


def team_logo_static_path(value):
    """直播 HUD 接口用的站内路径（/static/uploads/...），外部链接原样返回。"""
    path = logo_relative_path(value)
    if not path or path.startswith(("http://", "https://", "/")):
        return path
    return f"/static/uploads/{path}"

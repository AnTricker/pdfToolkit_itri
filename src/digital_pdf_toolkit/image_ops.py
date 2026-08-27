from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image


def natural_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("Preprocessing requires opencv-python-headless") from exc
    return cv2


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    import numpy as np
    cv2 = _cv2()
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def bgr_to_pil(image: np.ndarray) -> Image.Image:
    cv2 = _cv2()
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def rotate_quadrants(image: Image.Image, degrees: int) -> Image.Image:
    value = degrees % 360
    if value not in {0, 90, 180, 270}:
        raise ValueError("rotate override must be 0, 90, 180, or 270")
    return image.rotate(-value, expand=True, fillcolor="white") if value else image.copy()


def split_page(image: Image.Image, requested: str = "auto") -> tuple[list[tuple[str, Image.Image]], list[str]]:
    import numpy as np
    if requested == "single":
        return [("single", image.copy())], []
    if requested in {"left-to-right", "right-to-left"}:
        middle = image.width // 2
        values = [("left", image.crop((0, 0, middle, image.height))), ("right", image.crop((middle, 0, image.width, image.height)))]
        return (values if requested == "left-to-right" else list(reversed(values))), []
    if requested in {"top-to-bottom", "bottom-to-top"}:
        middle = image.height // 2
        values = [("top", image.crop((0, 0, image.width, middle))), ("bottom", image.crop((0, middle, image.width, image.height)))]
        return (values if requested == "top-to-bottom" else list(reversed(values))), []
    if requested != "auto":
        raise ValueError(f"Unsupported split mode: {requested}")

    cv2 = _cv2()
    gray = cv2.cvtColor(pil_to_bgr(image), cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    candidates: list[tuple[float, str, int]] = []
    for axis, projection, size in (
        ("vertical", ink.mean(axis=0), image.width),
        ("horizontal", ink.mean(axis=1), image.height),
    ):
        low, high = int(size * 0.35), int(size * 0.65)
        if high <= low:
            continue
        local = projection[low:high]
        offset = int(np.argmin(local))
        position = low + offset
        valley = float(local[offset])
        baseline = float(np.percentile(projection, 60)) + 1e-6
        confidence = max(0.0, 1.0 - valley / baseline)
        candidates.append((confidence, axis, position))
    if not candidates:
        return [("single", image.copy())], ["split_auto_low_confidence"]
    confidence, axis, position = max(candidates)
    minimum_content = 0.003
    if axis == "vertical":
        first_content = float(ink[:, :position].mean()) if position else 0.0
        second_content = float(ink[:, position:].mean()) if position < image.width else 0.0
    else:
        first_content = float(ink[:position, :].mean()) if position else 0.0
        second_content = float(ink[position:, :].mean()) if position < image.height else 0.0
    if confidence < 0.72 or min(first_content, second_content) < minimum_content:
        return [("single", image.copy())], ["split_auto_low_confidence"]
    if axis == "vertical":
        return [
            ("left", image.crop((0, 0, position, image.height))),
            ("right", image.crop((position, 0, image.width, image.height))),
        ], []
    return [
        ("top", image.crop((0, 0, image.width, position))),
        ("bottom", image.crop((0, position, image.width, image.height))),
    ], []


def perspective_correct(image: Image.Image) -> tuple[Image.Image, list[str]]:
    import numpy as np
    cv2 = _cv2()
    source = pil_to_bgr(image)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area = float(image.width * image.height)
    quadrilateral = None
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) == 4 and cv2.contourArea(polygon) >= area * 0.45:
            quadrilateral = polygon.reshape(4, 2).astype("float32")
            break
    if quadrilateral is None:
        return image.copy(), ["perspective_boundary_not_found"]
    sums = quadrilateral.sum(axis=1)
    diffs = np.diff(quadrilateral, axis=1).reshape(-1)
    ordered = np.array([
        quadrilateral[np.argmin(sums)], quadrilateral[np.argmin(diffs)],
        quadrilateral[np.argmax(sums)], quadrilateral[np.argmax(diffs)],
    ], dtype="float32")
    tl, tr, br, bl = ordered
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if width < 2 or height < 2:
        return image.copy(), ["perspective_invalid_boundary"]
    destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    result = cv2.warpPerspective(source, cv2.getPerspectiveTransform(ordered, destination), (width, height), borderValue=(255, 255, 255))
    return bgr_to_pil(result), []


def deskew(image: Image.Image) -> Image.Image:
    import numpy as np
    cv2 = _cv2()
    source = pil_to_bgr(image)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    points = np.column_stack(np.where(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1] > 0))
    if len(points) < 20:
        return image.copy()
    angle = cv2.minAreaRect(points[:, ::-1].astype("float32"))[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.15 or abs(angle) > 15:
        return image.copy()
    center = (source.shape[1] / 2, source.shape[0] / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    result = cv2.warpAffine(source, matrix, (source.shape[1], source.shape[0]), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return bgr_to_pil(result)


def correct_lighting(image: Image.Image) -> Image.Image:
    cv2 = _cv2()
    source = pil_to_bgr(image)
    lab = cv2.cvtColor(source, cv2.COLOR_BGR2LAB)
    light, a, b = cv2.split(lab)
    size = max(31, (min(source.shape[:2]) // 12) | 1)
    background = cv2.GaussianBlur(light, (size, size), 0)
    normalized = cv2.divide(light, background, scale=245)
    return bgr_to_pil(cv2.cvtColor(cv2.merge((normalized, a, b)), cv2.COLOR_LAB2BGR))


def denoise(image: Image.Image) -> Image.Image:
    cv2 = _cv2()
    return bgr_to_pil(cv2.bilateralFilter(pil_to_bgr(image), 5, 35, 35))


def enhance_contrast(image: Image.Image) -> Image.Image:
    cv2 = _cv2()
    source = pil_to_bgr(image)
    lab = cv2.cvtColor(source, cv2.COLOR_BGR2LAB)
    light, a, b = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(light)
    return bgr_to_pil(cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR))


def crop_blank_border(image: Image.Image) -> Image.Image:
    cv2 = _cv2()
    source = pil_to_bgr(image)
    gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)[1]
    points = cv2.findNonZero(mask)
    if points is None:
        return image.copy()
    x, y, width, height = cv2.boundingRect(points)
    padding = max(4, int(min(image.size) * 0.01))
    x0, y0 = max(0, x - padding), max(0, y - padding)
    x1, y1 = min(image.width, x + width + padding), min(image.height, y + height + padding)
    if (x1 - x0) * (y1 - y0) < image.width * image.height * 0.25:
        return image.copy()
    return image.crop((x0, y0, x1, y1))


def binarize(image: Image.Image, method: str) -> Image.Image:
    cv2 = _cv2()
    gray = cv2.cvtColor(pil_to_bgr(image), cv2.COLOR_BGR2GRAY)
    if method == "otsu":
        result = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    elif method == "adaptive":
        result = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 12)
    else:
        raise ValueError(f"Unsupported binarization method: {method}")
    return Image.fromarray(result).convert("RGB")

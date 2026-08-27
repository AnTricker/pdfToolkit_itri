from digital_pdf_toolkit.coordinates import RegionCoordinates, bbox_contains, rotate_bbox


def test_clockwise_rotation_uses_display_coordinates() -> None:
    assert rotate_bbox((10, 20, 30, 40), 100, 200, 90) == (160.0, 10.0, 180.0, 30.0)


def test_region_coordinate_spaces_map_to_render_pixels() -> None:
    assert RegionCoordinates((0.1, 0.2, 0.5, 0.6), "normalized_1").to_pixels(
        1000, 800, 500, 400
    ) == (100, 160, 500, 480)
    assert RegionCoordinates((100, 200, 500, 600), "normalized_1000").to_pixels(
        1000, 800, 500, 400
    ) == (100, 160, 500, 480)


def test_bbox_containment_tolerance() -> None:
    assert bbox_contains((0, 0, 10, 10), (1, 1, 9, 9))
    assert bbox_contains((0, 0, 10, 10), (-0.1, 1, 9, 9), tolerance=0.1)


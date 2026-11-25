import pytest

from app.schemas import Region
from app.services.facecam import infer_region


def test_stable_corner_crop_contains_faces_and_stays_inside_source():
    faces = [Region(x=600 + shift, y=5, width=28, height=30) for shift in (-3, -2, 0, 1, 3)]
    result = infer_region([[face] for face in faces] + [[], []], 640, 360)
    crop = result.region
    assert result.sampled_frames == 7 and result.matching_frames == 5
    assert crop is not None and crop.x + crop.width == 640 and crop.y == 0
    assert all(crop.x <= face.x and crop.y + crop.height >= face.y + face.height for face in faces)


@pytest.mark.parametrize("scenario", ["center", "transient", "ambiguous"])
def test_inconclusive_facecam_yields_no_crop(scenario):
    left = Region(x=35, y=22, width=30, height=30)
    right = Region(x=568, y=22, width=30, height=30)
    center = Region(x=298, y=155, width=44, height=44)
    frames = {
        "center": [[center]] * 7,
        "transient": [[left]] * 4 + [[], [], []],
        "ambiguous": [[left, right]] * 7,
    }
    assert infer_region(frames[scenario], 640, 360).region is None

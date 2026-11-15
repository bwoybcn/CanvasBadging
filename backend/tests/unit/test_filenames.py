# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from opencredential.api.filenames import file_stem


@pytest.mark.parametrize(
    ("title", "stem"),
    [
        (
            'Gŵyl Dewi 🎓 <img> & "Ysgol" Café \N{EN DASH} Ünïcödé',
            "gwyl-dewi-img-ysgol-cafe-unicode",
        ),
        ("Library Volunteer: 10 hours", "library-volunteer-10-hours"),
        ("Łódź", "odz"),
        ("中文", "badge"),
        ("", "badge"),
        (None, "badge"),
    ],
)
def test_stem_is_ascii_and_readable(title: str | None, stem: str) -> None:
    out = file_stem(title)
    assert out == stem
    out.encode("latin-1")  # must fit in a Content-Disposition header

"""Caption parsing checks runnable without installing external dependencies."""

from datetime import timedelta
import unittest

from file_server.data.caption import parse_caption


SAMPLE_CAPTION = (
    "[THÔNG BÁO] có TÀU khả nghi được phát hiện từ ảnh vệ tinh\n"
    "- Vị trí: [13.098, 114.094]\n"
    "- Thời gian: 2026-05-15 10:04:14\n"
    "- Dài / Rộng: 319.59(m)/70.37(m)\n"
    "- Tàu: S2C_MSIL2A_20260515T024531_N0512_R132_T49PHQ_20260515T061809_3"
)


class TestCaption(unittest.TestCase):
    def test_user_sample_preserves_utc_and_dimensions(self):
        result = parse_caption(SAMPLE_CAPTION)
        self.assertEqual(result.latitude, 13.098)
        self.assertEqual(result.longitude, 114.094)
        self.assertEqual(result.length_m, 319.59)
        self.assertEqual(result.width_m, 70.37)
        self.assertTrue(result.source_id.endswith("_3"))
        self.assertEqual(result.observed_at.isoformat(), "2026-05-15T10:04:14+00:00")

    def test_utc_midnight_boundary_is_not_converted(self):
        result = parse_caption(SAMPLE_CAPTION.replace("10:04:14", "23:04:14"))
        self.assertEqual(result.observed_at.date().isoformat(), "2026-05-15")
        self.assertEqual(result.observed_at.utcoffset(), timedelta(0))

    def test_missing_fields_and_invalid_dates_raise(self):
        for caption in ["- Tàu: abc", SAMPLE_CAPTION.replace("2026-05-15", "2026-02-30")]:
            with self.subTest(caption=caption), self.assertRaises(ValueError):
                parse_caption(caption)

    def test_html_and_signed_coordinates(self):
        caption = SAMPLE_CAPTION.replace("13.098", "-13.098").replace("- Tàu:", "- <b>Tàu:</b>")
        self.assertEqual(parse_caption(caption).latitude, -13.098)


if __name__ == "__main__":
    unittest.main()

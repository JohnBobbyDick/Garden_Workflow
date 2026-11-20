import pytest

from app.analyzers.sca.cvss import cvss3_base_score, severity_from_score
from app.analyzers.sca.versions import (
    UnsupportedVersion,
    compare_versions,
    in_range,
    parse_version,
)


class TestVersions:
    def test_trailing_zero_components_are_equal(self):
        assert compare_versions("1.9", "1.9.0") == 0

    def test_numeric_not_lexicographic(self):
        assert compare_versions("1.10.0", "1.9") > 0
        assert compare_versions("3.8.0", "3.9.0") < 0

    def test_single_numeric_component_date_versions(self):
        assert compare_versions("20230227", "20230618") < 0
        assert compare_versions("20231013", "20230618") > 0

    @pytest.mark.parametrize("raw", ["1.0-SNAPSHOT", "2.0.0.RELEASE", "1.+", "[1,2)", "", "1.0-rc1", "latest.release"])
    def test_qualified_or_dynamic_versions_unsupported(self, raw):
        with pytest.raises(UnsupportedVersion):
            parse_version(raw)

    def test_range_inclusive_exclusive_bounds(self):
        rng = {"lower": "1.5", "lowerInclusive": True, "upper": "1.10.0", "upperInclusive": False}
        assert in_range("1.9", rng)
        assert in_range("1.5", rng)
        assert not in_range("1.10.0", rng)
        assert not in_range("1.4.9", rng)

    def test_range_without_lower_bound(self):
        rng = {"lower": None, "lowerInclusive": False, "upper": "20230618", "upperInclusive": True}
        assert in_range("20230227", rng)
        assert in_range("20230618", rng)
        assert not in_range("20231013", rng)

    def test_version_above_upper_bound_not_vulnerable(self):
        rng = {"lower": None, "lowerInclusive": False, "upper": "3.18.0", "upperInclusive": False}
        assert not in_range("3.20.0", rng)


class TestCvss:
    @pytest.mark.parametrize(
        "vector,expected",
        [
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", 7.5),
            ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H", 8.1),
            ("CVSS:3.1/AV:L/AC:L/PR:N/UI:R/S:U/C:N/I:N/A:H", 5.5),
            ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N", 6.4),
            ("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
            ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N", 0.0),
            ("CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:H/I:N/A:N", 5.3),
        ],
    )
    def test_reference_vectors(self, vector, expected):
        assert cvss3_base_score(vector) == expected

    def test_invalid_vector_raises(self):
        with pytest.raises(ValueError):
            cvss3_base_score("CVSS:3.1/AV:X")

    @pytest.mark.parametrize(
        "score,sev", [(9.8, "CRITICAL"), (9.0, "CRITICAL"), (8.9, "HIGH"), (7.0, "HIGH"), (6.9, "MEDIUM"), (4.0, "MEDIUM"), (3.9, "LOW")]
    )
    def test_severity_bands(self, score, sev):
        assert severity_from_score(score) == sev

"""
Tests for sensitivity table correctness:
  1. Development-years hidden input stores the exact fractional value (no Math.ceil rounding).
  2. The sensitivity base-row ROI uses f.roi from calculateAll(), not a custom formula that
     double-counts opex/landRent.

These are static code-inspection tests — they guard against regression without a browser.
"""
import re
import unittest


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


BOARD_JS = 'assets/js/10-financial-report-timeline/03_timeline_board.js'
COLLECT_JS = 'assets/js/10-financial-report-timeline/01_report_collect.js'


class TestDevelopmentYearsFractional(unittest.TestCase):
    """The hidden #developmentYears input must store the exact fractional span,
    not Math.ceil(), so that 3 years 6 months stores 3.5 instead of 4."""

    def setUp(self):
        self.src = _read(BOARD_JS)

    def test_no_math_ceil_for_dev_years(self):
        """Math.ceil must not be used to compute nextDevYears."""
        # The old buggy pattern was: Math.ceil(.../ (365.25 * TIMELINE_DAY_MS))
        bad_pattern = re.compile(
            r'Math\.ceil\s*\(\s*\(period\.end\.ms\s*-\s*period\.start\.ms\)',
            re.DOTALL,
        )
        self.assertIsNone(
            bad_pattern.search(self.src),
            'Math.ceil() is still used for nextDevYears — dev duration will be rounded up.',
        )

    def test_math_round_used_for_dev_years(self):
        """Math.round(...* 100) / 100 pattern must be used to get a 2-dp fractional value."""
        good_pattern = re.compile(
            r'Math\.round\s*\(\s*\(period\.end\.ms\s*-\s*period\.start\.ms\)',
            re.DOTALL,
        )
        self.assertIsNotNone(
            good_pattern.search(self.src),
            'Expected Math.round-based exact fractional formula for nextDevYears.',
        )

    def test_fractional_scaling_100(self):
        """The rounding must include * 100 / 100 to preserve up to 2 decimal places."""
        self.assertIn('/ 100)', self.src,
                      'Expected "/ 100)" in dev-years formula for 2-decimal rounding.')


class TestSensitivityRoiUsesCalculateAllRoi(unittest.TestCase):
    """The sensitivity table must use f.roi from window.__financialProjection (which
    calculateAll() computes), not its own inline formula that double-counts expenses."""

    def setUp(self):
        self.src = _read(COLLECT_JS)

    def test_no_double_count_roi_formula(self):
        """The old broken pattern computed `out = adjustedProjectCost + totalExpenses`
        and then `profit = revenue - out`, double-counting opex and landRent
        because adjustedProjectCost already incorporates all costs."""
        bad_pattern = re.compile(
            r'out\s*=\s*\(f\.adjustedProjectCost\s*\|\|\s*0\)\s*\+\s*totalExpenses.*?'
            r'roi\s*:\s*out\s*>\s*0\s*\?\s*profit\s*/\s*out\s*:\s*null',
            re.DOTALL,
        )
        self.assertIsNone(
            bad_pattern.search(self.src),
            'Sensitivity ROI still uses the double-counting inline formula.',
        )

    def test_roi_uses_f_dot_roi(self):
        """Sensitivity push must use `roi: f.roi ?? null` to match calculateAll()."""
        pattern = re.compile(r'roi\s*:\s*f\.roi\s*\?\?\s*null')
        self.assertIsNotNone(
            pattern.search(self.src),
            'Expected `roi: f.roi ?? null` in renderSensitivity() push.',
        )


if __name__ == '__main__':
    unittest.main()

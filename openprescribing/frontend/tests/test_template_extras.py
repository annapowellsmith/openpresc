import datetime
import mock
import unittest

from frontend.templatetags import template_extras as t


class TestTemplateExtras(unittest.TestCase):
    def test_roundpound_less_than_10(self):
        self.assertEquals(t.roundpound(0.1), '0')
        self.assertEquals(t.roundpound(1), '1')
        self.assertEquals(t.roundpound(9), '9')
        self.assertEquals(t.roundpound(10), '10')

    def test_roundpound_more_than_10(self):
        self.assertEquals(t.roundpound(11), '10')
        self.assertEquals(t.roundpound(56), '60')
        self.assertEquals(t.roundpound(236), '200')
        self.assertEquals(t.roundpound(4999), '5,000')

    def test_deltawords_positive_all_sizes(self):
        self.assertEqual(t.deltawords(0, 100), "massively")
        self.assertEqual(t.deltawords(0, 29), "considerably")
        self.assertEqual(t.deltawords(0, 19), "moderately")
        self.assertEqual(t.deltawords(0, 1), "slightly")
        self.assertEqual(t.deltawords(0, 0), "not at all")

    def test_deltawords_negative(self):
        self.assertEqual(t.deltawords(29, 0), "considerably")

    @mock.patch('{.__name__}.timezone.now'.format(t))
    def test_current_time(self, timezone_now):
        timezone_now.return_value = datetime.date(2018, 1, 3)
        self.assertEqual(t.current_time('%Y-%m-%d'), '2018-01-03')

    def test_fancy_join(self):
        self.assertEqual(t.fancy_join(['a', 'b', 'c']), 'a, b and c')
        self.assertEqual(t.fancy_join(['a', 'b']), 'a and b')
        self.assertEqual(t.fancy_join(['a']), 'a')
        self.assertEqual(t.fancy_join([]), '')

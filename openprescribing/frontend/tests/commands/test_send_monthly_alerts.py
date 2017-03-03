# -*- coding: utf-8 -*-
import re
import unittest

from mock import patch
from mock import ANY

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from frontend.models import EmailMessage
from frontend.models import Measure
from frontend.management.commands.send_monthly_alerts import Command
from frontend.tests.test_bookmark_utils import _makeContext


CMD_NAME = 'send_monthly_alerts'


class AnyStringWith(str):
    def __eq__(self, other):
        return self in other


class ValidateOptionsTestCase(unittest.TestCase):
    def _defaultOpts(self, **extra):
        default = {
            'url': None,
            'ccg': None,
            'practice': None,
            'recipient_email': None,
            'url': None
        }
        for k, v in extra.items():
            default[k] = v
        return default

    def test_options_depended_on_by_recipient_email(self):
        opts = self._defaultOpts(url='thing')
        with self.assertRaises(CommandError):
            Command().validate_options(**opts)
        opts = self._defaultOpts(ccg='thing')
        with self.assertRaises(CommandError):
            Command().validate_options(**opts)
        opts = self._defaultOpts(practice='thing')
        with self.assertRaises(CommandError):
            Command().validate_options(**opts)

        opts = self._defaultOpts(practice='thing', recipient_email='thing')
        Command().validate_options(**opts)

    def test_incompatibile_options(self):
        opts = self._defaultOpts(url='thing', ccg='thing')
        with self.assertRaises(CommandError):
            Command().validate_options(**opts)
        opts = self._defaultOpts(url='thing', practice='thing')
        with self.assertRaises(CommandError):
            Command().validate_options(**opts)


class GetBookmarksTestCase(TestCase):
    fixtures = ['bookmark_alerts']

    def test_get_org_bookmarks_without_options(self):
        bookmarks = Command().get_org_bookmarks(recipient_email=None)
        active = all([x.user.is_active for x in bookmarks])
        self.assertEqual(len(bookmarks), 2)
        self.assertTrue(active)

    def test_get_org_bookmarks_with_options(self):
        bookmarks = Command().get_org_bookmarks(
            recipient_email='s@s.com',
            ccg='03V',
            practice='P87629'
        )
        self.assertEqual(len(bookmarks), 1)
        self.assertEqual(bookmarks[0].user.email, 's@s.com')
        self.assertTrue(bookmarks[0].user.profile.key)
        self.assertTrue(bookmarks[0].user.id)
        self.assertEqual(bookmarks[0].pct.code, '03V')
        self.assertEqual(bookmarks[0].practice.code, 'P87629')

    def test_get_search_bookmarks_without_options(self):
        bookmarks = Command().get_search_bookmarks(recipient_email=None)
        active = all([x.user.is_active for x in bookmarks])
        self.assertEqual(len(bookmarks), 1)
        self.assertEqual(bookmarks[0].url, 'foo')
        self.assertTrue(active)

    def test_get_search_bookmarks_with_options(self):
        bookmarks = Command().get_search_bookmarks(
            recipient_email='s@s.com',
            url='frob', search_name='baz')
        self.assertEqual(len(bookmarks), 1)
        self.assertEqual(bookmarks[0].user.email, 's@s.com')
        self.assertTrue(bookmarks[0].user.profile.key)
        self.assertTrue(bookmarks[0].user.id)
        self.assertEqual(bookmarks[0].url, 'frob')


@patch('frontend.views.bookmark_utils.InterestingMeasureFinder')
@patch('frontend.views.bookmark_utils.attach_image')
class OrgEmailTestCase(TestCase):
    fixtures = ['bookmark_alerts', 'measures']

    def test_email_recipient(self, attach_image, finder):
        test_context = _makeContext()
        call_mocked_command(test_context, finder)
        self.assertEqual(EmailMessage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        email_message = EmailMessage.objects.first()
        self.assertEqual(mail.outbox[-1].to, email_message.to)
        self.assertEqual(mail.outbox[-1].to, ['s@s.com'])

    def test_email_body_no_data(self, attach_image, finder):
        test_context = _makeContext()
        call_mocked_command(test_context, finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        # Name of the practice
        self.assertIn('1/ST ANDREWS MEDICAL PRACTICE', html)
        # Unsubscribe link
        self.assertIn('/bookmarks/dummykey', html)
        self.assertIn("We've no new information", html)

    def test_email_body_has_ga_tracking(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(declines=[(measure, 99.92, 0.12, 10.002)]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertRegexpMatches(
            html, '<a href=".*&utm_content=.*#cerazette".*>')

    def test_email_body_declines(self, attach_image, finder):
        attach_image.return_value = 'unique-image-id'
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(declines=[(measure, 99.92, 0.12, 10.002)]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn("this practice slipped", html)
        self.assertRegexpMatches(
            html, 'slipped massively .* on '
            '<a href=".*/practice/P87629/.*#cerazette".*>'
            'Cerazette vs. Desogestrel</a>')
        self.assertIn('<span class="worse"', html)
        self.assertIn('<img src="cid:unique-image-id', html)
        self.assertNotIn("Your best prescribing areas", html)
        self.assertNotIn("Cost savings", html)

    def test_email_body_two_declines(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(declines=[
                (measure, 99.92, 0.12, 10.002),
                (measure, 30, 10, 0),
            ]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertRegexpMatches(
            html, 'It also slipped considerably')

    def test_email_body_three_declines(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(declines=[
                (measure, 99.92, 0.12, 10.002),
                (measure, 30, 10, 0),
                (measure, 20, 10, 0)
            ]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertRegexpMatches(
            html, 'It also slipped:')
        self.assertRegexpMatches(
            html, re.compile('<ul.*<li>considerably on.*'
                             '<li>moderately on.*</ul>', re.DOTALL))

    def test_email_body_worst(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        attach_image.return_value = 'unique-image-id'
        call_mocked_command(_makeContext(worst=[measure]), finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn("We've found", html)
        self.assertRegexpMatches(
            html, re.compile(
                'the worst 10% on.*<a href=".*/practice/P87629'
                '/.*#cerazette".*>'
                "Cerazette vs. Desogestrel</a>", re.DOTALL))
        self.assertIn('<img src="cid:unique-image-id', html)

    def test_email_body_three_worst(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(worst=[measure, measure, measure]), finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertRegexpMatches(
            html, 'It was also in the worst 10% on:')
        self.assertRegexpMatches(
            html, re.compile('<ul.*<li>.*Desogestrel.*'
                             '<li>.*Desogestrel.*</ul>', re.DOTALL))

    def test_email_body_two_savings(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(possible_savings=[
                (measure, 9.9), (measure, 1.12)]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn(
            "These add up to around <b>£10</b> of "
            "potential savings".decode('utf-8'),
            html)
        self.assertRegexpMatches(
            html, '<li.*>\n<b>£10</b> on <a href=".*/practice/P87629'
            '/.*#cerazette".*>'
            "Cerazette vs. Desogestrel</a>".decode('utf-8'))

    def test_email_body_one_saving(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(possible_savings=[(measure, 9.9)]), finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn(
            "if it had prescribed in line with the average practice",
            html)
        self.assertRegexpMatches(
            html, 'it could have saved about <b>£10</b> on '
            '<a href=".*/practice/P87629/.*#cerazette".*>'
            "Cerazette vs. Desogestrel</a>".decode('utf-8'))

    def test_email_body_achieved_saving(self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(achieved_savings=[(measure, 9.9)]), finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn(
            "this practice saved around <b>£10".decode('utf-8'),
            html)

    def test_email_body_two_achieved_savings(
            self, attach_image, finder):
        measure = Measure.objects.get(pk='cerazette')
        call_mocked_command(
            _makeContext(
                achieved_savings=[(measure, 9.9), (measure, 12.0)]),
            finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn(
            "<li>\n<b>£10</b> on".decode('utf-8'),
            html)
        self.assertIn(
            "<li>\n<b>£10</b> on".decode('utf-8'),
            html)

    def test_email_body_total_savings(self, attach_image, finder):
        call_mocked_command(
            _makeContext(possible_top_savings_total=9000.1), finder)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        self.assertIn(
            "it could save around <b>£9,000</b>".decode('utf-8'),
            html)


@patch('frontend.views.bookmark_utils.attach_image')
class SearchEmailTestCase(TestCase):
    fixtures = ['bookmark_alerts']

    def test_all_recipients(self, attach_image):
        call_command(CMD_NAME)
        mail_queue = mail.outbox
        self.assertEqual(EmailMessage.objects.count(), 3)
        self.assertEqual(len(mail_queue), 3)

    def test_email_recipient(self, attach_image):
        opts = {'recipient_email': 's@s.com',
                'url': 'something',
                'search_name': 'some name'}
        call_command(CMD_NAME, **opts)
        self.assertEqual(EmailMessage.objects.count(), 1)
        email_message = EmailMessage.objects.first()
        self.assertEqual(email_message.send_count, 1)
        mail_queue = mail.outbox[-1]
        self.assertEqual(
            mail_queue.to, email_message.to)
        self.assertEqual(
            mail_queue.to, [opts['recipient_email']])
        self.assertEqual(
            mail_queue.extra_headers['message-id'], email_message.message_id)

    def test_email_message_id(self, attach_image):
        opts = {'recipient_email': 's@s.com',
                'url': 'something',
                'search_name': 'some name'}
        call_command(CMD_NAME, **opts)
        email_message = EmailMessage.objects.first()
        mail_queue = mail.outbox[-1]
        self.assertEqual(
            mail_queue.extra_headers['message-id'], email_message.message_id)

    def test_email_body(self, attach_image):
        opts = {'recipient_email': 's@s.com',
                'url': 'something',
                'search_name': 'some name'}
        call_command(CMD_NAME, **opts)
        message = mail.outbox[-1].alternatives[0]
        html = message[0]
        mime_type = message[1]
        self.assertIn(opts['search_name'], html)
        self.assertEquals(mime_type, 'text/html')

        self.assertIn('/bookmarks/dummykey', html)
        self.assertRegexpMatches(
            html, '<a href="http://localhost/analyse/.*#%s' % 'something')


def call_mocked_command(context, mock_finder, **opts):
    mock_finder.return_value.context_for_org_email.return_value = context
    default_opts = {'recipient_email': 's@s.com',
                    'ccg': '03V',
                    'practice': 'P87629'}
    for k, v in opts.items():
        default_opts[k] = v
    call_command(CMD_NAME, **default_opts)

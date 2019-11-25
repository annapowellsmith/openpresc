# coding=utf8
from django.conf import settings
from django.core import mail
from django.test import TestCase

from frontend.feedback import send_feedback_mail


class FeedbackTests(TestCase):
    def test_send_feedback_mail(self):
        mail.outbox = []

        send_feedback_mail(
            user_name="Alice Apple",
            user_email_addr="alice@example.com",
            subject="An apple a day...",
            message="...keeps the doctor away",
            url="https://openprescribing.net/bnf/090603/",
        )

        self.assertEqual(len(mail.outbox), 2)

        email = mail.outbox[0]

        expected_body = """New feedback from Alice Apple (alice@example.com) via https://openprescribing.net/bnf/090603/

~~~

...keeps the doctor away
"""

        self.assertEqual(email.to, [settings.SUPPORT_TO_EMAIL])
        self.assertEqual(email.from_email, "Alice Apple <feedback@openprescribing.net>")
        self.assertEqual(email.reply_to, ["alice@example.com"])
        self.assertEqual(email.subject, "OpenPrescribing Feedback: An apple a day...")
        self.assertEqual(email.body, expected_body)
        self.assertEqual(email.extra_headers["X-Mailgun-Track"], "no")

        email = mail.outbox[1]

        expected_body = """Hi Alice Apple,

This is a copy of the feedback you sent to the OpenPrescribing.net team.

~~~

...keeps the doctor away
"""

        self.assertEqual(email.to, ["alice@example.com"])
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(email.reply_to, [])
        self.assertEqual(email.subject, "OpenPrescribing Feedback: An apple a day...")
        self.assertEqual(email.body, expected_body)
        self.assertEqual(email.extra_headers["X-Mailgun-Track"], "no")

    def test_send_feedback_mail_name_escaped(self):
        mail.outbox = []

        send_feedback_mail(
            user_name="Alice Apple, NHS England",
            user_email_addr="alice@example.com",
            subject="",
            message="",
            url="",
        )
        email = mail.outbox[0]
        self.assertEqual(
            email.from_email,
            '"Alice Apple, NHS England" <feedback@openprescribing.net>',
        )

    def test_send_feedback_mail_nonascii_encoded(self):
        mail.outbox = []

        send_feedback_mail(
            user_name="Alicé Apple",
            user_email_addr="alice@example.com",
            subject="Test ✓",
            message="All Good ✓",
            url="http://example.com/?p=✓",
        )
        email = mail.outbox[0]
        self.assertEqual(
            email.from_email,
            "=?utf-8?q?Alic=C3=A9_Apple?= <feedback@openprescribing.net>",
        )
        self.assertEqual(email.subject, "OpenPrescribing Feedback: Test ✓")
        self.assertIn("All Good ✓", email.body)
        self.assertIn("http://example.com/?p=✓", email.body)

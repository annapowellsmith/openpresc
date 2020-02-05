# -*- coding: utf-8 -*-
from __future__ import print_function

import logging

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db.models import Q
from frontend.models import EmailMessage
from frontend.models import ImportLog
from frontend.models import OrgBookmark
from frontend.models import Profile
from frontend.models import SearchBookmark
from frontend.models import User
from frontend.models import Practice, PCT, PCN

from common.alert_utils import EmailErrorDeferrer
from frontend.views import bookmark_utils
from .send_all_england_alerts import send_alerts as send_all_england_alerts

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    args = ""
    help = """ Send monthly emails based on bookmarks. With no arguments, sends
    an email to every user for each of their bookmarks, for the
    current month. With arguments, sends a test email to the specified
    user for the specified organisation."""

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipient-email",
            help=("A single alert recipient to which the batch should be sent"),
        )
        parser.add_argument(
            "--recipient-email-file",
            help=(
                "The subset of alert recipients to which the batch should "
                "be sent. One email per line."
            ),
        )
        parser.add_argument(
            "--skip-email-file",
            help=(
                "The subset of alert recipients to which the batch should "
                "NOT be sent. One email per line."
            ),
        )
        parser.add_argument(
            "--ccg",
            help=(
                "If specified, a CCG code for which a test alert should be "
                "sent to `recipient-email`"
            ),
        )
        parser.add_argument(
            "--pcn",
            help=(
                "If specified, a PCN code for which a test alert "
                "should be sent to `recipient-email`"
            ),
        )
        parser.add_argument(
            "--practice",
            help=(
                "If specified, a Practice code for which a test alert "
                "should be sent to `recipient-email`"
            ),
        )
        parser.add_argument(
            "--search-name",
            help=(
                "If specified, a name (could be anything) for a test search "
                "alert about `url` which should be sent to "
                "`recipient-email`"
            ),
        )
        parser.add_argument(
            "--url",
            help=(
                "If specified, a URL for a test search "
                "alert with name `search-name` which should be sent to "
                "`recipient-email`"
            ),
        )
        parser.add_argument(
            "--max_errors",
            help="Max number of permitted errors before aborting the batch",
            default=3,
        )

    def get_org_bookmarks(self, now_month, **options):
        """Get all OrgBookmarks for active users who have not been sent a
        message tagged with `now_month`

        """
        query = (
            Q(user__is_active=True)
            & ~Q(user__emailmessage__tags__contains=["measures", now_month])
            &
            # Only include bookmarks for either a practice or pct: when both
            # are NULL this indicates an All England or PCN bookmark
            (Q(practice__isnull=False) | Q(pct__isnull=False))
        )
        if options["recipient_email"] and (
            options["ccg"] or options["practice"] or options["pcn"]
        ):
            dummy_user = User(email=options["recipient_email"], id="dummyid")
            dummy_user.profile = Profile(key="dummykey")
            bookmarks = [
                OrgBookmark(
                    user=dummy_user,
                    pct_id=options["ccg"],
                    practice_id=options["practice"],
                    pcn_id=options["pcn"],
                )
            ]
            logger.info("Created a single test org bookmark")
        elif options["recipient_email"] or options["recipient_email_file"]:
            recipients = []
            if options["recipient_email_file"]:
                with open(options["recipient_email_file"], "r") as f:
                    recipients = [x.strip() for x in f]
            else:
                recipients = [options["recipient_email"]]
            query = query & Q(user__email__in=recipients)
            bookmarks = OrgBookmark.objects.filter(query)
            logger.info("Found %s matching org bookmarks" % bookmarks.count())
        else:
            bookmarks = OrgBookmark.objects.filter(query)
            if options["skip_email_file"]:
                with open(options["skip_email_file"], "r") as f:
                    skip = [x.strip() for x in f]
                bookmarks = bookmarks.exclude(user__email__in=skip)
            logger.info("Found %s matching org bookmarks" % bookmarks.count())
        return bookmarks

    def get_search_bookmarks(self, now_month, **options):
        query = Q(user__is_active=True) & ~Q(
            user__emailmessage__tags__contains=["analyse", now_month]
        )
        if options["recipient_email"] and options["url"]:
            dummy_user = User(email=options["recipient_email"], id="dummyid")
            dummy_user.profile = Profile(key="dummykey")
            bookmarks = [
                SearchBookmark(
                    user=dummy_user, url=options["url"], name=options["search_name"]
                )
            ]
            logger.info("Created a single test search bookmark")
        elif not options["recipient_email"]:
            bookmarks = SearchBookmark.objects.filter(query)
            logger.info("Found %s matching search bookmarks" % bookmarks.count())
        else:
            query = query & Q(user__email=options["recipient_email"])
            bookmarks = SearchBookmark.objects.filter(query)
            logger.info("Found %s matching search bookmarks" % bookmarks.count())
        return bookmarks

    def validate_options(self, **options):
        if (options["url"] or options["ccg"] or options["practice"]) and not options[
            "recipient_email"
        ]:
            raise CommandError(
                "You must specify a test recipient email if you want to "
                "specify a test CCG, practice, or URL"
            )
        if options["url"] and (options["practice"] or options["ccg"]):
            raise CommandError(
                "You must specify either a URL, or one of a ccg or a practice"
            )

    def send_org_bookmark_email(self, org_bookmark, now_month, options):
        if org_bookmark.practice or options["practice"]:
            org = org_bookmark.practice or Practice.objects.get(pk=options["practice"])
        elif org_bookmark.pct or options["ccg"]:
            org = org_bookmark.pct or PCT.objects.get(pk=options["ccg"])
        elif org_bookmark.pcn or options["pcn"]:
            org = org_bookmark.pcn or PCN.objects.get(pk=options["pcn"])
        else:
            assert False

        stats = bookmark_utils.InterestingMeasureFinder(org).context_for_org_email()

        try:
            msg = bookmark_utils.make_org_email(org_bookmark, stats, tag=now_month)
            msg = EmailMessage.objects.create_from_message(msg)
            msg.send()
            logger.info(
                "Sent org bookmark alert to %s about %s" % (msg.to, org_bookmark.id)
            )
        except bookmark_utils.BadAlertImageError as e:
            logger.exception(e)

    def send_search_bookmark_email(self, search_bookmark, now_month):
        try:
            recipient_id = search_bookmark.user.id
            msg = bookmark_utils.make_search_email(search_bookmark, tag=now_month)
            msg = EmailMessage.objects.create_from_message(msg)
            msg.send()
            logger.info(
                "Sent search bookmark alert to %s about %s"
                % (recipient_id, search_bookmark.id)
            )
        except bookmark_utils.BadAlertImageError as e:
            logger.exception(e)

    def send_all_england_alerts(self, options):
        # The `send_all_england_alerts` command doesn't respect the same set of
        # options that this command does, so we only invoke it for certain
        # limited sets of options
        set_options = {k: v for (k, v) in options.items() if v is not None}
        # We can ignore all these options
        for key in [
            "pythonpath",
            "verbosity",
            "traceback",
            "settings",
            "no_color",
            "force_color",
            "max_errors",
            "skip_checks",
        ]:
            set_options.pop(key, None)
        # We do understand this one, so keep a record of its value
        recipient_email = set_options.pop("recipient_email", None)
        if not set_options:
            message = "Sending All England alerts"
            logger.info(message)
            print(message)
            send_all_england_alerts(recipient_email)
        else:
            message = "Not sending All England alerts as found unhandled option: {}".format(
                ", ".join(set_options.keys())
            )
            logger.info(message)
            print(message)

    def handle(self, *args, **options):
        self.validate_options(**options)
        now_month = (
            ImportLog.objects.latest_in_category("prescribing")
            .current_at.strftime("%Y-%m-%d")
            .lower()
        )
        with EmailErrorDeferrer(int(options["max_errors"])) as error_deferrer:
            for org_bookmark in self.get_org_bookmarks(now_month, **options):
                error_deferrer.try_email(
                    self.send_org_bookmark_email, org_bookmark, now_month, options
                )

            for search_bookmark in self.get_search_bookmarks(now_month, **options):
                error_deferrer.try_email(
                    self.send_search_bookmark_email, search_bookmark, now_month
                )
        self.send_all_england_alerts(options)

# -*- coding: utf-8 -*-
from datetime import date
from tempfile import NamedTemporaryFile
import HTMLParser
import logging
import re
import subprocess
import urllib
import urlparse

from anymail.message import attach_inline_image_file
from dateutil.relativedelta import relativedelta
from premailer import Premailer
import numpy as np
import pandas as pd

from django.conf import settings
from django.contrib.humanize.templatetags.humanize import apnumber
from django.core.mail import EmailMultiAlternatives
from django.core.urlresolvers import reverse
from django.template.loader import get_template
from django.utils.safestring import mark_safe

from common.utils import email_as_text
from common.utils import nhs_titlecase
from frontend.models import ImportLog
from frontend.models import Measure
from frontend.models import MeasureValue

GRAB_CMD = ('/usr/local/bin/phantomjs ' +
            settings.SITE_ROOT +
            '/frontend/management/commands/grab_chart.js')

logger = logging.getLogger(__name__)


class CUSUM(object):
    """See Introduction to Statistical Quality Control, Montgomery DC, Wiley, 2009
    and our paper
    http://dl4a.org/uploads/pdf/581SPC.pdf
    """
    def __init__(self, data, window_size=12, sensitivity=5):
        data = np.array(map(lambda x: np.nan
                            if x is None else x, data))
        ## Remove sufficient leading nulls to ensure we can start with
        ## any value
        self.start_index = 0
        while pd.isnull(data[self.start_index:self.start_index+window_size]).all():
            if self.start_index > len(data):
                data = []
                start_index = 0
                break
            self.start_index += 1
        self.data = data
        self.window_size = window_size
        self.sensitivity = sensitivity
        self.pos_cusums = []
        self.neg_cusums = []
        self.target_means = []
        self.alert_thresholds = []
        self.alert_indices = []
        self.pos_alerts = []
        self.neg_alerts = []

    def work(self):
        for i, datum in enumerate(self.data):
            if i <= self.start_index:
                # If they're all nans, advance
                window = self.data[i:self.window_size+i]
                self.new_target_mean(window)
                self.new_alert_threshold(window)
                self.compute_cusum(datum, reset=True)
            elif self.cusum_within_alert_threshold():
                # Note this will always be true for the first `window_size`
                # data points
                self.maintain_target_mean()
                self.maintain_alert_threshold()
                self.compute_cusum(datum)
            else:
                # Assemble a moving window of the last `window_size`
                # non-null values
                window = self.data[i-self.window_size:i]
                self.new_target_mean(window)
                if self.moving_in_same_direction(datum):  # this "peeks ahead"
                    self.maintain_alert_threshold()
                    self.compute_cusum(datum)
                else:
                    self.new_alert_threshold(window)  # uses window
                    self.compute_cusum(datum, reset=True)
            # Record alert
            if self.cusum_below_alert_threshold():
                self.record_alert(datum, i, kind='down')
            elif self.cusum_above_alert_threshold():
                self.record_alert(datum, i, kind='up')
            else:
                self.record_alert(datum, i, kind=None)

        return {'smax': self.pos_cusums, 'smin': self.neg_cusums,
                'target_mean': self.target_means,
                'alert_threshold': self.alert_thresholds,
                'alert': self.alert_indices,
                'alert_percentile_pos': self.pos_alerts,
                'alert_percentile_neg': self.neg_alerts}

    def moving_in_same_direction(self, datum):
        # Peek ahead to see what the next CUSUM would be
        next_pos_cusum, next_neg_cusum = self.compute_cusum(datum, store=False)
        going_up = (next_pos_cusum > self.current_pos_cusum() and
                    self.cusum_above_alert_threshold())
        going_down = (next_neg_cusum < self.current_neg_cusum() and
                      self.cusum_below_alert_threshold())
        return going_up or going_down

    def __repr__(self):
        return """
        data:           {data}
        pos_cusums:     {pos_cusums}
        neg_cusums:     {neg_cusums}
        target_means:   {target_means}
        alert_thresholds: {alert_thresholds}"
        """.format(**self.__dict__)

    def record_alert(self, datum, i, kind=None):
        assert kind in ['up', 'down', None]
        if kind == 'up':
            self.alert_indices.append(i)
            self.pos_alerts.append(datum)
            self.neg_alerts.append(None)
        elif kind == 'down':
            self.alert_indices.append(i)
            self.pos_alerts.append(None)
            self.neg_alerts.append(datum)
        else:
            self.pos_alerts.append(None)
            self.neg_alerts.append(None)

    def maintain_alert_threshold(self):
        self.alert_thresholds.append(self.alert_thresholds[-1])
        return self.alert_thresholds[-1]

    def maintain_target_mean(self):
        self.target_means.append(self.target_means[-1])
        return self.target_means[-1]

    def cusum_above_alert_threshold(self):
        return self.pos_cusums[-1] > self.alert_thresholds[-1]

    def cusum_below_alert_threshold(self):
        return self.neg_cusums[-1] < -self.alert_thresholds[-1]

    def cusum_within_alert_threshold(self):
        return not (self.cusum_above_alert_threshold() or
                self.cusum_below_alert_threshold())

    def new_target_mean(self, window):
        self.target_means.append(
            np.nanmean(window))

    def new_alert_threshold(self, window):
        self.alert_thresholds.append(
            np.nanstd(window * self.sensitivity))  # XXX didn't other version use n-1?

    def current_pos_cusum(self):
        return self.pos_cusums[-1]

    def current_neg_cusum(self):
        return self.neg_cusums[-1]

    def compute_cusum(self, datum, reset=False, store=True):
        alert_threshold = self.alert_thresholds[-1]
        delta = 0.5 * alert_threshold / self.sensitivity
        current_mean = self.target_means[-1]
        cusum_pos = datum - (current_mean + delta)
        cusum_neg = datum - (current_mean - delta)
        if not reset:
            cusum_pos += self.pos_cusums[-1]
            cusum_neg += self.neg_cusums[-1]
        cusum_pos = max(0, cusum_pos)
        cusum_neg = min(0, cusum_neg)
        if store:
            self.pos_cusums.append(cusum_pos)
            self.neg_cusums.append(cusum_neg)
        return cusum_pos, cusum_neg



def remove_jagged(measurevalues):
    """Remove records that are outside the standard error of the mean or
    where they hit 0% or 100% more than once.

    Bit of a guess as to if this'll work or not. Pending review by
    real statistician.

    """
    values = [x.percentile for x in measurevalues]
    sem = (np.std(values) /
           np.sqrt(len(values)))
    keep = []
    extremes = 0
    for x in measurevalues:
        if x.measure.is_percentage:
            if x.calc_value == 1.0:
                extremes += 1
        if x.calc_value == 0.0:
            extremes += 1
        if x.numerator and x.numerator < 15:
            extremes += 1
        if extremes > 1 or x.percentile < sem or x.percentile > (100 - sem):
            next
        else:
            keep.append(x)
    return keep


def remove_jagged_logit(measurevalues):
    """Remove records that are outside the standard error of the mean.

    Bit of a guess as to if this'll work or not. Pending review by
    real statistivcian.

    """
    values = []
    for m in measurevalues:
        val = m.percentile / 100.0
        if val > 0 and val < 1:
            values.append(np.log(val/(100-val)))
        else:
            values.append(
                np.log(
                    (val + 0.5/len(measurevalues)) /
                    (1 - val + (0.5/len(measurevalues)))
                )
            )
    sem = (np.std(values) /
           np.sqrt(len(values)))
    keep = []
    for m in measurevalues:
        if m.percentile < sem or m.percentile > (100 - sem):
            next
        else:
            keep.append(m)
    return keep


def cusum(data, months_smoothing, sensitivity):
    """performs the CUSUM algorithm on input data string"""
    # convert missing percentile values from None to numpy nan
    data = np.array(map(lambda x: np.nan
                        if x is None else x, data))
    smax = [0]
    smin = [0]
    # set target_mean and alert_threshold at start
    # & if alert_threshold reached
    non_missing_percentiles = data[~np.isnan(data)]

    # the reference percentile is the first N non-missing months.  is
    # this correct? Should it actually include the nulls? Let's wait
    # to see how we reset the reference later.
    target_mean = [
        np.mean(non_missing_percentiles[0:months_smoothing])]

    # relative to how close all the measurements are to the mean. So
    # if they deviate from the mean by a total of X...
    alert_threshold = [
        np.std(non_missing_percentiles[0:months_smoothing]) * sensitivity]
    alert = []
    alert_percentile_pos = [None]
    alert_percentile_neg = [None]
    # we never get an alert at position len(data). Why?
    for i in range(1, len(data)):
        if smax[i-1] > alert_threshold[i-1] or smin[i-1] < -alert_threshold[i-1]:
            # generate temp smax/smin
            # Windows where n = 3
            #      1, 2, 3, 4, 5, 6
            # ref  -  -  -
            # i=1  -
            # i=2  -  -
            # i=3  -  -  -
            # i=4     -  -  -
            # i=5        -  -  -
            #
            # initial ref perc:  2
            # initial alert_threshold: 0.408
            #      1, x, 3, 4, 5, 6
            # ref  -     -  -
            # i=1  -
            # i=2  -
            # i=3  -     -
            # i=4        -  -
            # i=5        -  -  -
            # initial ref per: 2.67
            # initial alert_threshold: 0.624
            window = data[i-months_smoothing:i]

            # smax is C+
            # smin is C-
            # C+ is cumulative difference between current value and the current mean + slack value (K)
            # so "target_mean" should be "target_mean", alert_threshold should be current_slack_value.
            # alert_threshold is defined as half of the difference between the next mean and the current one

            # Define H = hs and K = ks, where s is the standard deviation of the sample variable
            # used in forming the cusum. Using h = 4 or h = 5 and k = 0.5 gives good results

            # So that means we want to use a target mean of the first
            # N values, then when we go outside it, reset the target
            # mean to be what? Should it include the sample variable or not?

            # And what about K


            # for any `i`, the window is everything up to but not
            # including it; the calculated cusum is based on a mean
            # that doesn't include it and on a stddev before *that*, the
            target_mean.append(np.nanmean(window))
            smax_temp = (max(0, data[i] - (target_mean[i] +
                                           (0.5 * alert_threshold[i-1] /
                                            sensitivity)) + smax[i-1]))
            smin_temp = (min(0, data[i] - (target_mean[i] -
                                           (0.5 * alert_threshold[i-1] /
                                            sensitivity)) + smin[i-1]))

            #test whether change still occuring *IN THE SAME DIRECTION*
            ## positive change
            if smax[i-1] < smax_temp and smax[i-1] > alert_threshold[i-1]:
                alert_threshold.append(alert_threshold[i-1])
                smax.append(smax_temp)
                smin.append(smin_temp)
                alert.append(i-1)
                alert_percentile_pos.append(data[i])
                alert_percentile_neg.append(None)
            ## negative change
            elif smin[i-1] > smin_temp and smin[i-1] < -alert_threshold[i-1]:
                alert_threshold.append(alert_threshold[i-1])
                smax.append(smax_temp)
                smin.append(smin_temp)
                alert.append(i-1)
                alert_percentile_pos.append(None)
                alert_percentile_neg.append(data[i])
            ## if not, reset
            else:
                alert.append(i-1)
                alert_threshold.append(np.std(data[i-months_smoothing:i]
                                [~np.isnan(data[i-months_smoothing:i])])
                                 * sensitivity) # +remove nan values
                #reset smax/smin to 0
                #modified to include the value for the current month
                smax.append(max(0, data[i] - (target_mean[i] +
                                              (0.5 * alert_threshold[i] /
                                               sensitivity))))
                smin.append(min(0, data[i] - (target_mean[i] -
                                              (0.5 * alert_threshold[i] /
                                               sensitivity))))
                alert_percentile_pos.append(None)
                alert_percentile_neg.append(None)
        #else append previous values
        else:
            target_mean.append(target_mean[i-1])
            alert_threshold.append(alert_threshold[i-1])

            #calculate smax/smin XXX I think this should be i-1
            smax.append(max(0, data[i] - (target_mean[i] +
                                          (0.5 * alert_threshold[i] /
                                           sensitivity)) + smax[i-1]))
            smin.append(min(0, data[i] - (target_mean[i] -
                                          (0.5 * alert_threshold[i] /
                                           sensitivity)) + smin[i-1]))
            if smax[i] > alert_threshold[i]:
                alert_percentile_pos.append(data[i])
                alert_percentile_neg.append(None)
            elif smin[i] < -alert_threshold[i]:
                alert_percentile_neg.append(data[i])
                alert_percentile_pos.append(None)
            else:
                alert_percentile_pos.append(None)
                alert_percentile_neg.append(None)
    return {'smax':smax, 'smin':smin,
            'target_mean':target_mean,
            'alert_threshold':alert_threshold,
            'alert':alert,
            'alert_percentile_pos':alert_percentile_pos,
            'alert_percentile_neg':alert_percentile_neg}


class InterestingMeasureFinder(object):
    def __init__(self, practice=None, pct=None,
                 interesting_saving=1000,
                 interesting_percentile_change=10):
        assert practice or pct
        self.practice = practice
        self.pct = pct
        self.interesting_percentile_change = interesting_percentile_change
        self.interesting_saving = interesting_saving

    def months_ago(self, period):
        now = ImportLog.objects.latest_in_category('prescribing').current_at
        return now + relativedelta(months=-(period-1))

    def _best_or_worst_performing_in_period(self, period, best_or_worst=None):
        assert best_or_worst in ['best', 'worst']
        worst = []
        for measure in Measure.objects.all():
            measure_filter = {
                'measure': measure, 'month__gte': self.months_ago(period)}
            if self.practice:
                measure_filter['practice'] = self.practice
            else:
                measure_filter['pct'] = self.pct
                measure_filter['practice'] = None
            invert_percentile_for_comparison = False
            if measure.low_is_good:
                if best_or_worst == 'worst':
                    invert_percentile_for_comparison = True
                    measure_filter['percentile__gte'] = 90
                else:
                    measure_filter['percentile__lte'] = 10
            else:
                if best_or_worst == 'worst':
                    measure_filter['percentile__lte'] = 10
                else:
                    invert_percentile_for_comparison = True
                    measure_filter['percentile__gte'] = 90
            is_worst = remove_jagged(
                MeasureValue.objects.filter(**measure_filter))
            if len(is_worst) == period:
                if invert_percentile_for_comparison:
                    comparator = 100 - is_worst[-1].percentile
                else:
                    comparator = is_worst[-1].percentile
                worst.append((measure, comparator))
        worst = sorted(worst, key=lambda x: x[-1])
        return [x[0] for x in worst]

    def worst_performing_in_period(self, period):
        """Return every measure where the organisation specified in the given
        bookmark is in the worst decile for each month in the
        specified time range

        """
        return self._best_or_worst_performing_in_period(period, 'worst')

    def best_performing_in_period(self, period):
        """Return every measure where organisations specified in the given
        bookmark is in the best decile for each month in the specified
        time range

        """
        return self._best_or_worst_performing_in_period(period, 'best')

    def most_change_in_period(self, period):
        """Every measure where the specified organisation has changed by more
        than 10 centiles in the specified time period, ordered by rate
        of change.

        The rate of change is worked out using a line of best fit.

        Returns a list of triples of (measure, change_from, change_to)

        """
        improvements = []
        declines = []
        for measure in Measure.objects.all():
            measure_filter = {
                'measure': measure,
                'month__gte': self.months_ago(period),
                'percentile__isnull': False
            }
            if self.practice:
                measure_filter['practice'] = self.practice
            else:
                measure_filter['pct'] = self.pct
                measure_filter['practice'] = None
            percentiles = MeasureValue.objects.filter(
                **measure_filter).order_by('month').values_list(
                    'percentile', flat=True)
            if len(percentiles) == period:
                x = np.arange(period)
                y = np.array(percentiles)
                p, res, _, _, _ = np.polyfit(x, y, 1, full=True)
                m, b = p
                residuals = res[0]
                start_centile = b
                end_centile = m * (period - 1) + b
                if residuals < 1200:
                    delta = start_centile - end_centile
                    data = (m, measure, start_centile,
                            end_centile, residuals)
                    if delta >= self.interesting_percentile_change:
                        if measure.low_is_good:
                            improvements.append(data)
                        else:
                            declines.append(data)
                    elif delta <= (0 - self.interesting_percentile_change):
                        if measure.low_is_good:
                            declines.append(data)
                        else:
                            improvements.append(data)

        improvements = sorted(improvements, key=lambda x: -abs(x[0]))
        declines = sorted(declines, key=lambda x: -abs(x[0]))
        return {'improvements': [d[1:] for d in improvements],
                'declines': [d[1:] for d in declines]}

    def top_and_total_savings_in_period(self, period):
        """Sum total possible savings over time, and find measures where
        possible or achieved savings are greater than self.interesting_saving.

        Returns a dictionary where the keys are
        `possible_top_savings_total`, `possible_savings` and
        `achieved_savings`; and the values are an integer, sorted
        `(measure, saving)` tuples, and sorted `(measure, saving)`
        tuples respectively.

        """
        possible_savings = []
        achieved_savings = []
        total_savings = 0
        for measure in Measure.objects.all():
            if measure.is_cost_based:
                measure_filter = {
                    'measure': measure, 'month__gte': self.months_ago(period)}
                if self.practice:
                    measure_filter['practice'] = self.practice
                else:
                    measure_filter['pct'] = self.pct
                    measure_filter['practice'] = None
                values = list(
                    MeasureValue.objects.filter(**measure_filter))
                if len(values) != period:
                    continue
                savings_at_50th = [
                    x.cost_savings['50'] for x in
                    values]
                savings_or_loss_for_measure = sum(savings_at_50th)
                if savings_or_loss_for_measure >= self.interesting_saving:
                    possible_savings.append(
                        (measure, savings_or_loss_for_measure)
                    )
                if savings_or_loss_for_measure <= -self.interesting_saving:
                    achieved_savings.append(
                        (measure, -1 * savings_or_loss_for_measure))
                if measure.low_is_good:
                    savings_at_10th = sum([
                        max(0, x.cost_savings['10']) for x in
                        values])
                else:
                    savings_at_10th = sum([
                        max(0, x.cost_savings['90']) for x in
                        values])
                total_savings += savings_at_10th
        return {
            'possible_savings': sorted(
                possible_savings, key=lambda x: -x[1]),
            'achieved_savings': sorted(
                achieved_savings, key=lambda x: x[1]),
            'possible_top_savings_total': total_savings
        }

    def _move_non_ordinal(self, from_list, to_list):
        for measure in from_list[:]:
            if type(measure) == tuple:
                # As returned by most_changing function
                m = measure[0]
            else:
                m = measure
            if m.low_is_good is None:
                from_list.remove(measure)
                if measure not in to_list:
                    to_list.append(measure)

    def context_for_org_email(self):
        worst = self.worst_performing_in_period(3)
        best = self.best_performing_in_period(3)
        most_changing = self.most_change_in_period(9)
        interesting = []
        most_changing_interesting = []
        for extreme in [worst, best]:
            self._move_non_ordinal(extreme, interesting)
        for extreme in [most_changing['improvements'],
                        most_changing['declines']]:
            self._move_non_ordinal(extreme, most_changing_interesting)
        return {
            'interesting': interesting,
            'most_changing_interesting': most_changing_interesting,
            'worst': worst,
            'best': best,
            'most_changing': most_changing,
            'top_savings': self.top_and_total_savings_in_period(6)}


def attach_image(msg, url, file_path, selector, dimensions='1024x1024'):
    if 'selectedTab=map' in url:
        wait = 8000
        dimensions = '1000x600'
    elif 'selectedTab=chart' in url:
        wait = 1000
        dimensions = '800x600'
    elif 'selectedTab' in url:
        wait = 500
        dimensions = '800x600'
    else:
        wait = 1000
    cmd = '{cmd} "{host}{url}" {file_path} "{selector}" {dimensions} {wait}'
    cmd = (
        cmd.format(
            cmd=GRAB_CMD,
            host=settings.GRAB_HOST,
            url=url,
            file_path=file_path,
            selector=selector,
            dimensions=dimensions,
            wait=wait
        )
    )
    result = subprocess.check_output(cmd, shell=True)
    logger.debug("Command %s completed with output %s" % (cmd, result.strip()))
    return attach_inline_image_file(
        msg, file_path, subtype='png')


def getIntroText(stats, org_type):
    declines = len(stats['most_changing']['declines'])
    improvements = len(stats['most_changing']['improvements'])
    possible_savings = len(stats['top_savings']['possible_savings'])
    worst = len(stats['worst'])
    best = len(stats['best'])
    not_great = worst + declines
    pretty_good = best + improvements
    msg = ""
    in_sentence = False
    if not_great or pretty_good or possible_savings:
        if not_great:
            msg = "We've found %s prescribing measure%s where this %s " % (
                apnumber(not_great),
                not_great > 1 and 's' or '',
                org_type)
            in_sentence = True
            if declines and worst:
                msg += "is <span class='worse'>getting worse, or could be "
                msg += "doing better</span>"
            elif declines:
                msg += "is <span class='worse'>getting worse</span>"
            else:
                msg += "could be <span class='worse'>doing better</span>"
        else:
            msg = ("Good news: we've not found any problem prescribing "
                   "measures for this %s!" % org_type)
            in_sentence = False
        if pretty_good:
            if msg and in_sentence:
                msg += ", and %s measure%s where it " % (
                    apnumber(pretty_good),
                    pretty_good > 1 and 's' or '')
            else:
                msg = ("We've found %s prescribing measure%s where "
                       "this %s " % (apnumber(pretty_good),
                                     pretty_good > 1 and 's' or '',
                                     org_type))
            if best and improvements:
                msg += "is <span class='better'>doing well</span>."
            elif improvements:
                msg += "is <span class='better'>improving</span>."
            else:
                msg += "is <span class='better'>already doing "
                msg += "very well</span>."
            in_sentence = False
        if in_sentence:
            msg += ". "
        if possible_savings:
            if msg:
                msg += " We've also found "
            else:
                msg = "We've found "
            msg += ("%s prescribing measure%s where there are some "
                    "potential cost savings." % (
                        apnumber(possible_savings),
                        possible_savings > 1 and 's' or ''))
    else:
        msg = ("We've no new information about this %s this month! "
               "Its performance is not an outlier on any "
               "of our common prescribing measures." % org_type)
    return mark_safe(msg)


def _hasStats(stats):
    return (stats['worst'] or
            stats['best'] or
            stats['interesting'] or
            stats['most_changing_interesting'] or
            stats['top_savings']['possible_top_savings_total'] or
            stats['top_savings']['possible_savings'] or
            stats['top_savings']['achieved_savings'] or
            stats['most_changing']['declines'] or
            stats['most_changing']['improvements'])


def ga_tracking_qs(context):
    tracking_params = {
        'utm_medium': 'email',
        'utm_campaign': context['campaign_name'],
        'utm_source': context['campaign_source'],
        'utm_content': context['email_id']
    }
    return urllib.urlencode(tracking_params)


def truncate_subject(prefix, subject):
    assert subject, "Subject must not be empty"
    max_length = 78 - len(prefix) - len(settings.EMAIL_SUBJECT_PREFIX)
    ellipsis = '...'
    subject = nhs_titlecase(subject)
    if len(subject) <= max_length:
        truncated = subject
    else:
        if 'by' in subject:
            end_bit = subject.split('by')[-1]
            end_bit = 'by' + end_bit
        else:
            end_bit = ''
        start_bit = subject[:(max_length - len(end_bit) - len(ellipsis))]
        truncated = start_bit + ellipsis + end_bit
    return prefix + truncated


def make_email_with_campaign(bookmark, campaign_source):
    campaign_name = "monthly alert %s" % date.today().strftime("%Y-%m-%d")
    email_id = "/email/%s/%s/%s" % (
        campaign_name,
        campaign_source,
        bookmark.id)
    subject_prefix = 'Your monthly update about '
    msg = EmailMultiAlternatives(
        truncate_subject(subject_prefix, bookmark.name),
        "This email is only available in HTML",
        settings.SUPPORT_EMAIL,
        [bookmark.user.email])
    metadata = {"subject": msg.subject,
                "campaign_name": campaign_name,
                "campaign_source": campaign_source,
                "email_id": email_id}
    msg.metadata = metadata
    msg.qs = ga_tracking_qs(metadata)
    # Set the message id now, so we can reuse it
    msg.extra_headers = {'message-id': msg.message()['message-id']}
    return msg


def make_org_email(org_bookmark, stats):
    msg = make_email_with_campaign(org_bookmark, 'dashboard-alerts')
    dashboard_uri = (
        settings.GRAB_HOST + org_bookmark.dashboard_url() +
        '?' + msg.qs)
    html_email = get_template('bookmarks/email_for_measures.html')
    with NamedTemporaryFile(suffix='.png') as getting_worse_file, \
            NamedTemporaryFile(suffix='.png') as still_bad_file, \
            NamedTemporaryFile(suffix='.png') as interesting_file:
        most_changing = stats['most_changing']
        getting_worse_img = still_bad_img = interesting_img = None
        if most_changing['declines']:
            getting_worse_img = attach_image(
                msg,
                org_bookmark.dashboard_url(),
                getting_worse_file.name,
                '#' + most_changing['declines'][0][0].id
            )
        if stats['worst']:
            still_bad_img = attach_image(
                msg,
                org_bookmark.dashboard_url(),
                still_bad_file.name,
                '#' + stats['worst'][0].id)
        if stats['interesting']:
            interesting_img = attach_image(
                msg,
                org_bookmark.dashboard_url(),
                interesting_file.name,
                '#' + stats['interesting'][0].id)
        unsubscribe_link = settings.GRAB_HOST + reverse(
            'bookmark-login',
            kwargs={'key': org_bookmark.user.profile.key})
        html = html_email.render(
            context={
                'intro_text': getIntroText(
                    stats, org_bookmark.org_type()),
                'total_possible_savings': sum(
                    [x[1] for x in
                     stats['top_savings']['possible_savings']]),
                'has_stats': _hasStats(stats),
                'domain': settings.GRAB_HOST,
                'measures_count': Measure.objects.count(),
                'getting_worse_image': getting_worse_img,
                'still_bad_image': still_bad_img,
                'interesting_image': interesting_img,
                'bookmark': org_bookmark,
                'dashboard_uri': mark_safe(dashboard_uri),
                'qs': mark_safe(msg.qs),
                'stats': stats,
                'unsubscribe_link': unsubscribe_link
            })
        html = Premailer(
            html, cssutils_logging_level=logging.ERROR).transform()
        html = unescape_href(html)
        text = email_as_text(html)
        msg.body = text
        msg.attach_alternative(html, "text/html")
        msg.extra_headers['list-unsubscribe'] = "<%s>" % unsubscribe_link
        msg.tags = ["monthly_update", "measures"]
        return msg


def make_search_email(search_bookmark):
    msg = make_email_with_campaign(search_bookmark, 'analyse-alerts')
    html_email = get_template('bookmarks/email_for_searches.html')
    parsed_url = urlparse.urlparse(search_bookmark.dashboard_url())
    if parsed_url.query:
        qs = '?' + parsed_url.query + '&' + msg.qs
    else:
        qs = '?' + msg.qs
    dashboard_uri = (
        settings.GRAB_HOST + parsed_url.path + qs + '#' + parsed_url.fragment)
    with NamedTemporaryFile(suffix='.png') as graph_file:
        graph = attach_image(
            msg,
            search_bookmark.dashboard_url(),
            graph_file.name,
            '#results .tab-pane.active'
        )
        unsubscribe_link = settings.GRAB_HOST + reverse(
            'bookmark-login',
            kwargs={'key': search_bookmark.user.profile.key})
        html = html_email.render(
            context={
                'bookmark': search_bookmark,
                'domain': settings.GRAB_HOST,
                'graph': graph,
                'dashboard_uri': mark_safe(dashboard_uri),
                'unsubscribe_link': unsubscribe_link
            })
        html = Premailer(
            html, cssutils_logging_level=logging.ERROR).transform()
        html = unescape_href(html)
        text = email_as_text(html)
        msg.body = text
        msg.attach_alternative(html, "text/html")
        msg.extra_headers['list-unsubscribe'] = "<%s>" % unsubscribe_link
        msg.tags = ["monthly_update", "analyse"]
        return msg


def unescape_href(text):
    """Unfortunately, premailer escapes hrefs and there's [not much we can
    do about it](https://github.com/peterbe/premailer/issues/72).
    Unencode them again."""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', text)
    html_parser = HTMLParser.HTMLParser()
    for href in hrefs:
        text = text.replace(href, html_parser.unescape(href))
    return text

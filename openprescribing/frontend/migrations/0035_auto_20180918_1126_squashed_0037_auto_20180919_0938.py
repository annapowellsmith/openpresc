# -*- coding: utf-8 -*-
# Generated by Django 1.11.15 on 2018-09-19 08:47
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [(b'frontend', '0035_auto_20180918_1126'), (b'frontend', '0036_auto_20180919_0929'), (b'frontend', '0037_auto_20180919_0938')]

    dependencies = [
        ('frontend', '0034_practice_ccg_change_reason'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='presentation',
            name='active_quantity',
        ),
        migrations.RemoveField(
            model_name='presentation',
            name='adq',
        ),
        migrations.RemoveField(
            model_name='presentation',
            name='adq_unit',
        ),
        migrations.RemoveField(
            model_name='presentation',
            name='percent_of_adq',
        ),
        migrations.AddField(
            model_name='presentation',
            name='adq_per_quantity',
            field=models.FloatField(blank=True, null=True),
        ),
    ]

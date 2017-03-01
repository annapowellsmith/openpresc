# -*- coding: utf-8 -*-
# Generated by Django 1.9.1 on 2017-03-01 16:27
from __future__ import unicode_literals

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('frontend', '0020_remove_maillog_email'),
    ]

    operations = [
        migrations.AlterField(
            model_name='maillog',
            name='tags',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(db_index=True, max_length=100), null=True, size=None),
        ),
    ]

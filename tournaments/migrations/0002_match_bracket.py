from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='bracket',
            field=models.CharField(
                choices=[('winners', 'Winners'), ('losers', 'Losers'), ('grand_final', 'Grand Final')],
                default='winners',
                max_length=20,
            ),
        ),
        migrations.AlterUniqueTogether(
            name='match',
            unique_together={('tournament', 'bracket', 'round_number', 'match_number')},
        ),
        migrations.AlterField(
            model_name='tournament',
            name='format',
            field=models.CharField(
                choices=[
                    ('single_elim', 'Single Elimination'),
                    ('double_elim', 'Double Elimination'),
                    ('round_robin', 'Round Robin'),
                ],
                default='single_elim',
                max_length=20,
            ),
        ),
    ]

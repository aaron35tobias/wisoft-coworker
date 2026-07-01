from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_profile_profile_picture'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='banner_image',
            field=models.ImageField(blank=True, null=True, upload_to='profile_banners/'),
        ),
    ]

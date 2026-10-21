from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Backup


@receiver(post_delete, sender=Backup)
def delete_backup_file(sender, instance, **kwargs):
    """При удалении записи из журнала удаляет и файл копии на сервере.

    Копия на Яндекс Диске остается — ее удаляет ротация или вы вручную.
    """
    path = instance.local_path
    if path and path.exists():
        path.unlink()

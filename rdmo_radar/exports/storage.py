"""Local persistence after confirmed RADAR creation; separate from import staging."""
from django.db import transaction

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_radar.exceptions import ExportStoreError


def store_export_result(project, set_index, radar_id, radar_url) -> None:
    """Store confirmed results directly, with rollback and safe errors independent of a service."""
    set_index = int(set_index)
    try:
        with transaction.atomic():
            for path, text in (('project/dataset/radar_id', radar_id), ('project/dataset/radar_url', radar_url)):
                try:
                    attribute = Attribute.objects.get(path=path)
                except Attribute.DoesNotExist:
                    continue
                Value.objects.update_or_create(
                    project=project, attribute=attribute, snapshot=None, set_prefix='',
                    set_index=set_index, collection_index=0, defaults={'text': text},
                )
    except Exception as error:
        raise ExportStoreError(set_index, radar_id, radar_url) from error

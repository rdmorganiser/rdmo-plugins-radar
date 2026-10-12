"""Local persistence after confirmed RADAR creation; separate from import staging."""
from django.db import transaction

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value

from rdmo_radar.exceptions import ExportStoreError


def store_export_result(project, set_index, radar_id, radar_url, *, set_prefix='', destinations=None) -> None:
    """Store confirmed results directly, with rollback and safe errors independent of a service."""
    set_index = int(set_index)
    try:
        with transaction.atomic():
            for path, text in (('project/dataset/radar_id', radar_id), ('project/dataset/radar_url', radar_url)):
                name = path.rsplit('/', 1)[-1]
                destination = destinations.get(name, {}) if destinations is not None else {}
                if destination is None:
                    raise ValueError('RADAR result destination is ambiguous or lacks scalar coordinates.')
                try:
                    attribute = Attribute.objects.get(uri=destination['uri']) if destination else Attribute.objects.get(
                        path=path,
                    )
                except Attribute.DoesNotExist:
                    continue
                Value.objects.update_or_create(
                    project=project, attribute=attribute, snapshot=None,
                    set_prefix=destination.get('set_prefix', set_prefix),
                    set_index=destination.get('set_index', set_index), collection_index=0, defaults={'text': text},
                )
    except Exception as error:
        raise ExportStoreError(set_index, radar_id, radar_url) from error

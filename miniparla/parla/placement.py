# TODO (bozhi): We may need a `placement` module to hold these `get_placement_for_xxx` interfaces, which makes more sense than the `tasks` module here. Check imports when doing so.

from typing import Collection, Iterable, Union, List, Any, FrozenSet
from parla.device import Device, Architecture, get_all_devices
from parla.task_runtime import TaskID, Task


PlacementSource = Union[Architecture, Device, Task, TaskID, Any]

def get_placement_for_value(p: PlacementSource) -> List[Device]:
    if hasattr(p, "__parla_placement__"):
        # this handles Architecture, ResourceRequirements, and other types with __parla_placement__
        return list(p.__parla_placement__())
    elif isinstance(p, Device):
        return [p]
    elif isinstance(p, TaskID):
        return get_placement_for_value(p.task)
    elif isinstance(p, task_runtime.Task):
        return get_placement_for_value(p.req)
    elif array.is_array(p):
        return [array.get_memory(p).device]
    elif isinstance(p, Collection):
        raise TypeError("Collection passed to get_placement_for_value, probably needed get_placement_for_set: {}"
                        .format(type(p)))
    else:
        raise TypeError(type(p))


def get_placement_for_set(placement: Collection[PlacementSource]) -> FrozenSet[Device]:
    if not isinstance(placement, Collection):
        raise TypeError(type(placement))
    return frozenset(d for p in placement for d in get_placement_for_value(p))


def get_placement_for_any(placement: Union[Collection[PlacementSource], Any, None]) \
        -> FrozenSet[Device]:
    if placement is not None:
        ps = placement if isinstance(placement, Iterable) and not array.is_array(
            placement) else [placement]
        return get_placement_for_set(ps)
    else:
        return frozenset(get_all_devices())
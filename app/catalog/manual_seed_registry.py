from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules

import app.catalog.seeds as seed_package
from app.catalog.manual_seed_types import ManualProductSeed


def _load_manual_seeds() -> tuple[ManualProductSeed, ...]:
    seeds: list[ManualProductSeed] = []

    for module_info in iter_modules(seed_package.__path__):
        module_name = module_info.name

        if module_name.startswith("_"):
            continue

        module = import_module(f"{seed_package.__name__}.{module_name}")
        seed = getattr(module, "SEED", None)

        if seed is None:
            continue

        if not isinstance(seed, ManualProductSeed):
            raise TypeError(
                f"{module.__name__}.SEED must be a ManualProductSeed instance"
            )

        seeds.append(seed)

    return tuple(sorted(seeds, key=lambda item: item.key))


SEED_LIST: tuple[ManualProductSeed, ...] = _load_manual_seeds()

SEEDS: dict[str, ManualProductSeed] = {
    seed.key: seed for seed in SEED_LIST
}


def get_manual_seed(key: str) -> ManualProductSeed:
    try:
        return SEEDS[key]
    except KeyError as exc:
        available = ", ".join(sorted(SEEDS))
        raise KeyError(f"Unknown manual seed '{key}'. Available seeds: {available}") from exc

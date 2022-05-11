from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING
from diot import Diot

if TYPE_CHECKING:
    from ..cmdy_bakeable import Bakeable


def register_plugins(bakeable: "Bakeable"):
    out = Diot()
    for path in Path(__file__).parent.glob("*.py"):
        if path.name.startswith("_"):
            continue

        module = import_module(f".{path.stem}", package=__package__)
        out[path.stem] = module.vendor(bakeable)

    return out

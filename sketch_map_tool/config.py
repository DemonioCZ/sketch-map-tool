import os
from types import MappingProxyType
from typing import Dict

import toml

from sketch_map_tool.helpers import get_project_root


def get_config_path() -> str:
    """Get configuration file path

    Read value of the environment variable 'SMT_CONFIG' or use default 'config.toml'
    """
    default = str(get_project_root() / "config" / "config.toml")
    return os.getenv("SMT_CONFIG", default=default)


def load_config_default() -> Dict[str, str | int | float]:
    return {
        "data-dir": get_default_data_dir(),
        "user-agent": "sketch-map-tool",
        "broker-url": "redis://localhost:6379",
        "result-backend": "db+postgresql://smt:smt@localhost:5432",
        "wms-url-osm": "https://maps.heigit.org/osm-carto/service?SERVICE=WMS&VERSION=1.1.1",
        "wms-layers-osm": "heigit:osm-carto@2xx",
        "wms-url-esri-world-imagery": "https://maps.heigit.org/sketch-map-tool/service?SERVICE=WMS&VERSION=1.1.1",
        "wms-layers-esri-world-imagery": "world_imagery",
        "wms-read-timeout": 600,
        "max-nr-simultaneous-uploads": 100,
        "max_pixel_per_image": 10e8,  # 10.000*10.000
        "neptune_project": "HeiGIT/SketchMapTool",
        "neptune_api_token": "",
        "neptune_model_id_yolo_osm_cls": "SMT-CLR-1",
        "neptune_model_id_yolo_esri_cls": "SMT-CLR-3",
        "neptune_model_id_yolo_osm_obj": "SMT-OSM-9",
        "neptune_model_id_yolo_esri_obj": "SMT-ESRI-1",
        "neptune_model_id_sam": "SMT-SAM-1",
        "model_type_sam": "vit_b",
        "esri-api-key": "",
        "log-level": "INFO",
    }


def load_config_from_file(path: str) -> Dict[str, str]:
    """Load configuration from file on disk."""
    if os.path.isfile(path):
        with open(path, "r") as f:
            return toml.load(f)
    else:
        return {}


def get_config() -> MappingProxyType:
    """Get configuration variables from environment and file.

    Configuration values from file will be given precedence over default values.
    """
    cfg = load_config_default()
    cfg_file = load_config_from_file(get_config_path())
    cfg.update(cfg_file)
    return MappingProxyType(cfg)


def get_config_value(key: str) -> str:
    config = get_config()
    return config[key]


def get_default_data_dir() -> str:
    return str(get_project_root() / "data")

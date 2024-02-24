import os
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

from celery.result import AsyncResult
from celery.signals import worker_process_init, worker_process_shutdown
from geojson import FeatureCollection
from numpy.typing import NDArray
from segment_anything import SamPredictor, sam_model_registry
from ultralytics import YOLO
from ultralytics_4bands import YOLO as YOLO_4

from sketch_map_tool import celery_app as celery
from sketch_map_tool import get_config_value, map_generation
from sketch_map_tool.database import client_celery as db_client_celery
from sketch_map_tool.helpers import to_array
from sketch_map_tool.models import Bbox, Layer, PaperFormat, Size
from sketch_map_tool.oqt_analyses import generate_pdf as generate_report_pdf
from sketch_map_tool.oqt_analyses import get_report
from sketch_map_tool.upload_processing import (
    clip,
    georeference,
    merge,
    polygonize,
    post_process,
)
from sketch_map_tool.upload_processing.detect_markings import detect_markings
from sketch_map_tool.upload_processing.ml_models import init_model
from sketch_map_tool.wms import client as wms_client


@worker_process_init.connect
def init_worker(**kwargs):
    """Initializing database connection for worker"""
    db_client_celery.open_connection()


@worker_process_shutdown.connect
def shutdown_worker(**kwargs):
    """Closing database connection for worker"""
    db_client_celery.close_connection()


# 1. GENERATE SKETCH MAP & QUALITY REPORT
#
@celery.task()
def generate_sketch_map(
    uuid: UUID,
    bbox: Bbox,
    format_: PaperFormat,
    orientation: str,  # TODO: is not accessed
    size: Size,
    scale: float,
    layer: Layer,
) -> BytesIO | AsyncResult:
    """Generate and returns a sketch map as PDF and stores the map frame in DB."""
    raw = wms_client.get_map_image(bbox, size, layer)
    map_image = wms_client.as_image(raw)
    qr_code_ = map_generation.qr_code(
        str(uuid),
        bbox,
        layer,
        format_,
    )
    map_pdf, map_img = map_generation.generate_pdf(
        map_image,
        qr_code_,
        format_,
        scale,
        layer,
    )
    db_client_celery.insert_map_frame(map_img, uuid)
    return map_pdf


@celery.task()
def generate_quality_report(bbox: Bbox) -> BytesIO | AsyncResult:
    """Generate a quality report as PDF.

    Fetch quality indicators from the OQT API
    """
    report = get_report(bbox)
    return generate_report_pdf(report)


# 2. DIGITIZE RESULTS
#
@celery.task()
def georeference_sketch_maps(
    file_ids: list[int],
    file_names: list[str],
    uuids: list[str],
    map_frames: dict[str, NDArray],
    bboxes: list[Bbox],
) -> AsyncResult | BytesIO:
    def process(sketch_map_id: int, uuid: str, bbox: Bbox) -> BytesIO:
        """Process a Sketch Map."""
        # r = interim result
        r = db_client_celery.select_file(sketch_map_id)
        r = to_array(r)
        r = clip(r, map_frames[uuid])
        r = georeference(r, bbox)
        return r

    def zip_(file: BytesIO, file_name: str):
        with ZipFile(buffer, "a") as zip_file:
            name = ".".join(file_name.split(".")[:-1])
            zip_file.writestr(f"{name}.geotiff", file.read())

    buffer = BytesIO()
    for file_id, uuid, bbox, file_name in zip(file_ids, uuids, bboxes, file_names):
        zip_(process(file_id, uuid, bbox), file_name)
    buffer.seek(0)
    return buffer


@celery.task()
def digitize_sketches(
    file_ids: list[int],
    file_names: list[str],
    uuids: list[str],
    map_frames: dict[str, NDArray],
    layer_types: list[str],
    bboxes: list[Bbox],
) -> AsyncResult | FeatureCollection:
    # Initialize ml-models. This has to happen inside of celery context.
    #
    # Prevent usage of CUDA while transforming Tensor objects to numpy arrays
    # during marking detection
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    # Custom trained model for object detection of markings and colors
    if "OSM" in layer_types:
        yolo_path_osm = init_model(get_config_value("neptune_model_id_yolo_osm_obj"))
        yolo_model_osm_obj: YOLO_4 = YOLO_4(yolo_path_osm)
    if "ELSE" in layer_types:
        yolo_path_esri = init_model(get_config_value("neptune_model_id_yolo_esri_obj"))
        yolo_model_esri_obj: YOLO_4 = YOLO_4(yolo_path_esri)

    if "OSM" not in layer_types and "ESRI" not in layer_types:
        raise ValueError("Unexpected layer type, only OSM and ESRI are supported")

    yolo_path_cls = init_model(get_config_value("neptune_model_id_yolo_cls"))
    yolo_model_cls: YOLO = YOLO(yolo_path_cls)

    # Zero shot segment anything model
    sam_path = init_model(get_config_value("neptune_model_id_sam"))
    sam_model = sam_model_registry[get_config_value("model_type_sam")](sam_path)
    sam_predictor: SamPredictor = SamPredictor(sam_model)  # mask predictor

    l = []  # noqa: E741
    for file_id, file_name, uuid, bbox, layer in zip(
        file_ids, file_names, uuids, bboxes, layer_types
    ):
        # r = interim result
        r: BytesIO = db_client_celery.select_file(file_id)  # type: ignore
        r: NDArray = to_array(r)  # type: ignore
        r: NDArray = clip(r, map_frames[uuid])  # type: ignore
        if layer == "OSM":
            yolo_model_obj = yolo_model_osm_obj
        elif layer == "ESRI":
            yolo_model_obj = yolo_model_esri_obj
        else:
            raise ValueError(
                f"Unexpected layer type {layer} only OSM and ESRI are supported"
            )

        r: NDArray = detect_markings(r, yolo_model_obj, yolo_model_cls, sam_predictor)  # type: ignore
        # m = marking
        for m in r:
            m: BytesIO = georeference(m, bbox, bgr=False)  # type: ignore
            m: FeatureCollection = polygonize(m, layer_name=file_name)  # type: ignore
            m: FeatureCollection = post_process(m, file_name)
            l.append(m)
    return merge(l)

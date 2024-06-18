from io import BytesIO
from uuid import UUID, uuid4

import pytest
from psycopg2.extensions import connection

from sketch_map_tool.database import client_celery, client_flask
from sketch_map_tool.exceptions import (
    CustomFileDoesNotExistAnymoreError,
    CustomFileNotFoundError,
)


@pytest.fixture
def map_frame_old(flask_app, uuid_create, map_frame):
    """Mock map frame which is uploaded a year ago."""
    # NOTE: Maybe mocking a map frame in the database with fake file
    with flask_app.app_context():
        update_query = (
            "UPDATE map_frame SET ts = NOW() - INTERVAL '6 months' WHERE uuid = %s"
        )
        with client_flask.open_connection().cursor() as curs:
            curs.execute(update_query, [uuid_create])

    yield map_frame

    map_frame.seek(0)
    with flask_app.app_context():
        update_query = "UPDATE map_frame SET file = %s WHERE uuid = %s"
        with client_flask.open_connection().cursor() as curs:
            curs.execute(update_query, [map_frame.getvalue(), uuid_create])
    map_frame.seek(0)


@pytest.fixture
def sketch_map_without_consent(flask_app, uuid_create, sketch_map_marked):
    """mock uploaded sketch map without consent."""
    with flask_app.app_context():
        update_query = "UPDATE blob SET consent = FALSE WHERE uuid = %s;"
        with client_flask.open_connection().cursor() as curs:
            curs.execute(update_query, [uuid_create])

        yield sketch_map_marked
        update_query = """
            UPDATE
                blob
            SET
                consent = TRUE,
                file = %s,
                file_name = 'sketch_map.png'
            WHERE
                uuid = %s;
        """
        with client_flask.open_connection().cursor() as curs:
            curs.execute(update_query, [sketch_map_marked, uuid_create])


def test_open_connection():
    client_celery.db_conn = None
    client_celery.open_connection()
    assert isinstance(client_celery.db_conn, connection)


def test_close_closed_connection():
    client_celery.db_conn = None
    client_celery.close_connection()
    assert client_celery.db_conn is None
    client_celery.open_connection()


def test_close_open_connection():
    assert isinstance(client_celery.db_conn, connection)
    client_celery.close_connection()
    assert client_celery.db_conn.closed != 0  # 0 if the connection is open
    client_celery.open_connection()


def test_write_map_frame(flask_app, map_frame, bbox, format_, orientation, layer):
    uuid = uuid4()
    client_celery.insert_map_frame(map_frame, uuid, bbox, format_, orientation, layer)
    with flask_app.app_context():
        file, bbox, layer = client_flask.select_map_frame(uuid)
        assert isinstance(file, bytes)
        assert bbox == str(bbox)
        assert layer == (layer)


def test_delete_map_frame(flask_app, map_frame, bbox, format_, orientation, layer):
    uuid = uuid4()
    client_celery.insert_map_frame(map_frame, uuid, bbox, format_, orientation, layer)
    with flask_app.app_context():
        # do not raise a FileNotFoundError_
        client_flask.select_map_frame(uuid)
    client_celery.delete_map_frame(uuid)
    with pytest.raises(CustomFileNotFoundError):
        with flask_app.app_context():
            client_flask.select_map_frame(uuid)


def test_cleanup_map_frames_recent(
    uuid_create: str,
    map_frame: BytesIO,
    flask_app,
):
    """Map frame has been generated recently.

    Nothing should happen.
    """
    client_celery.cleanup_map_frames()
    with flask_app.app_context():
        # should not raise an error / should not delete the map frame
        map_frame_, _, _ = client_flask.select_map_frame(UUID(uuid_create))
    assert map_frame_ == map_frame.getvalue()


@pytest.mark.usefixtures("uuid_digitize")
def test_cleanup_map_frames_recent_with_consent(
    uuid_create: str,
    map_frame: BytesIO,
    flask_app,
):
    """Map frame has been generated recently & sketch map uploaded with consent.

    Nothing should happen.
    """
    client_celery.cleanup_map_frames()
    with flask_app.app_context():
        # should not raise an error / should not delete the map frame
        map_frame_received, _, _ = client_flask.select_map_frame(UUID(uuid_create))
    assert map_frame_received == map_frame.getvalue()


@pytest.mark.usefixtures("sketch_map_without_consent")
def test_cleanup_map_frames_recent_without_consent(
    uuid_create: str,
    map_frame: BytesIO,
    flask_app,
):
    """Map frame has been generated recently and sketch map is uploaded without consent.

    Nothing should happen.
    """
    # TODO:
    client_celery.cleanup_map_frames()
    with flask_app.app_context():
        # should not raise an error / should not delete the map frame
        map_frame_received, _, _ = client_flask.select_map_frame(UUID(uuid_create))
    assert map_frame_received == map_frame.getvalue()


@pytest.mark.usefixtures("uuid_digitize")
def test_cleanup_map_frames_old_with_consent(
    uuid_create: str,
    map_frame_old: BytesIO,
    flask_app,
):
    """Map frame has been generated a year ago & sketch map uploaded with consent.

    Nothing should happen.
    """
    client_celery.cleanup_map_frames()
    # should not raise an error / should not delete the map frame
    with flask_app.app_context():
        map_frame_received, _, _ = client_flask.select_map_frame(UUID(uuid_create))
    assert map_frame_received == map_frame_old.getvalue()


@pytest.mark.usefixtures("map_frame_old", "sketch_map_without_consent")
def test_cleanup_map_frames_old_without_consent(
    uuid_create: str,
    flask_app,
):
    """Map frame has been generated a year ago & sketch map uploaded without consent.

    Map frame file content should be set to null.
    """
    # map frame file content should be delete
    client_celery.cleanup_map_frames()
    with flask_app.app_context():
        with pytest.raises(CustomFileDoesNotExistAnymoreError):
            client_flask.select_map_frame(UUID(uuid_create))


@pytest.mark.usefixtures("uuid_digitize")
def test_cleanup_blobs_with_consent(
    flask_app,
    uuid_create: str,
    sketch_map_marked: bytes,
):
    """Sketch map has been uploaded with consent. Nothing should happen."""
    client_celery.cleanup_blob([UUID(uuid_create)])
    with flask_app.app_context():
        with client_flask.open_connection().cursor() as curs:
            curs.execute("SELECT file FROM blob WHERE uuid = %s", [uuid_create])
            result = curs.fetchone()
            assert result is not None
            assert result[0] == sketch_map_marked


@pytest.mark.usefixtures("uuid_digitize", "sketch_map_without_consent")
def test_cleanup_blobs_without_consent(flask_app, uuid_create: str):
    """Sketch map has been uploaded without consent.

    Sketch map file and name should be set to null.
    """
    client_celery.cleanup_blob([UUID(uuid_create)])
    with flask_app.app_context():
        with client_flask.open_connection().cursor() as curs:
            curs.execute(
                "SELECT file, file_name FROM blob WHERE uuid = %s", [uuid_create]
            )
            result = curs.fetchone()
            assert result is not None
            for r in result:
                assert r is None

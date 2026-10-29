"""Optional real local-service integration, no model inference.

Run with QDRANT_TEST_URL=http://127.0.0.1:6333 python3 -m pytest -q.
Uses a uniquely named temporary collection and removes only that collection.
"""
from dataclasses import replace
import os
import uuid

import pytest

from media_search.config import Settings
from media_search.store import Store


@pytest.mark.skipif(not os.getenv("QDRANT_TEST_URL"), reason="Local Qdrant service not selected")
def test_real_service_persistence_pagination_and_filtering(tmp_path):
    url = os.environ["QDRANT_TEST_URL"]
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        pytest.fail("This offline integration check only targets a local Qdrant service.")
    s = Settings(data_dir=tmp_path, qdrant_url=url,
                 collection="cookbook_test_" + uuid.uuid4().hex, dimensions=3)
    store = Store(s)
    try:
        store.ensure()
        ids = []
        for index in range(5):
            id_ = str(uuid.uuid4())
            ids.append(id_)
            kind = "image" if index < 3 else "video"
            store.upsert(id_, [1., 0., 0.] if kind == "image" else [0., 1., 0.],
                dict(kind=kind, title=str(index), source_name="fixture",
                     media_path="fixture.jpg", thumbnail_path="fixture.jpg",
                     start_seconds=None, end_seconds=None))
        # Reconnect over HTTP: the database outlives the Python client.
        store.close()
        store = Store(s)
        store.ensure()
        assert store.count() == 5
        first = store.browse(limit=2)
        second = store.browse(limit=2, offset=first["next_offset"])
        third = store.browse(limit=2, offset=second["next_offset"])
        found = [x["id"] for page in (first, second, third) for x in page["items"]]
        assert len(found) == len(set(found)) == 5
        assert third["next_offset"] is None
        assert len(store.browse(kind="video")["items"]) == 2
        assert len(store.search([1., 0., 0.], kind="image")) == 3
        assert all(x["kind"] == "video" for x in store.search([0., 1., 0.], kind="video"))
        with pytest.raises(ValueError, match="contract differs"):
            Store(replace(s, model="different"), store.client).ensure()
    finally:
        store.client.delete_collection(s.collection)
        store.close()

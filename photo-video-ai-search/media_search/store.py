from urllib.parse import quote

from qdrant_client import QdrantClient, models

from .config import Settings


class Store:
    def __init__(self, settings: Settings, client: QdrantClient | None = None):
        self.settings = settings
        self.client = client or QdrantClient(url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None, timeout=30)

    def close(self):
        self.client.close()

    def ensure(self):
        s = self.settings
        if not self.client.collection_exists(s.collection):
            self.client.create_collection(s.collection, vectors_config={s.vector_name:
                models.VectorParams(size=s.dimensions, distance=models.Distance.COSINE)})
        vectors = self.client.get_collection(s.collection).config.params.vectors
        if not isinstance(vectors, dict) or set(vectors) != {s.vector_name}:
            raise ValueError("Collection embedding contract differs; use a new QDRANT_COLLECTION and re-ingest.")
        params = vectors[s.vector_name]
        if params.size != s.dimensions or params.distance != models.Distance.COSINE:
            raise ValueError("Collection vector size/distance differs; use a new QDRANT_COLLECTION.")

    def existing(self, point_id):
        return bool(self.client.retrieve(self.settings.collection, [point_id], with_payload=False))

    def upsert(self, point_id, vector, payload):
        self.client.upsert(self.settings.collection, points=[models.PointStruct(
            id=point_id, vector={self.settings.vector_name: vector}, payload=payload)], wait=True)

    def count(self):
        return self.client.count(self.settings.collection, exact=True).count

    @staticmethod
    def item(point):
        payload = point.payload or {}
        return {"id": str(point.id), **{key: payload.get(key) for key in
                ("kind", "title", "source_name", "start_seconds", "end_seconds")},
                "media_url": "/media/" + quote(payload["media_path"], safe="/"),
                "thumbnail_url": "/media/" + quote(payload["thumbnail_path"], safe="/"),
                "score": getattr(point, "score", None)}

    def gallery(self, limit=24):
        return self.browse(limit=limit)["items"]

    def browse(self, limit=24, kind="all", offset=None):
        filter_ = None if kind == "all" else models.Filter(must=[
            models.FieldCondition(key="kind", match=models.MatchValue(value=kind))])
        points, next_offset = self.client.scroll(self.settings.collection, limit=limit,
            scroll_filter=filter_, offset=offset, with_payload=True, with_vectors=False)
        return {"items": [self.item(p) for p in points],
                "next_offset": str(next_offset) if next_offset is not None else None}

    def search(self, vector, kind="all", limit=12):
        filter_ = None if kind == "all" else models.Filter(must=[
            models.FieldCondition(key="kind", match=models.MatchValue(value=kind))])
        points = self.client.query_points(self.settings.collection, query=vector,
            using=self.settings.vector_name, query_filter=filter_, limit=limit,
            with_payload=True, with_vectors=False).points
        return [self.item(p) for p in points]

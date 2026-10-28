"""Embeddings por la API paga y vectores de modelos distintos que no se mezclan en el RAG."""

from afterdrive.ia import llm
from afterdrive.ingesta.embeddings import coseno, vector_de


def test_embeddings_por_la_api_paga(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_API_KEY", "pg-key")
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.setenv("PAGA_EMB_MODEL", "emb-pago")
    posts = []

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(llm, "_transporte", {"post": lambda url, **kw: posts.append((url, kw)) or R(), "get": None})
    assert llm.embeber(["frenos"]) == [[0.1, 0.2]]
    url, kw = posts[0]
    assert url == "https://api.paga.test/v1/embeddings"
    assert kw["json"] == {"model": "emb-pago", "input": ["frenos"]}  # sin input_type: es de NVIDIA
    assert kw["headers"] == {"Authorization": "Bearer pg-key"}
    assert llm.modelo_embeddings() == "paga/emb-pago"


def test_api_paga_sin_modelo_de_embeddings_sigue_por_nvidia(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_API_KEY", "pg-key")
    monkeypatch.delenv("PAGA_EMB_MODEL", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("NVIDIA_EMB_MODEL", "nemotron")
    assert llm.modelo_embeddings() == "nvidia/nemotron"


def test_vectores_de_otro_modelo_no_se_comparan():
    assert vector_de({"embedding": [1.0], "embedding_modelo": "paga/emb"}, "paga/emb") == [1.0]
    assert vector_de({"embedding": [1.0], "embedding_modelo": "nvidia/x"}, "paga/emb") is None
    assert vector_de({"embedding": [1.0]}, "paga/emb") == [1.0]  # legado sin etiqueta
    assert coseno([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0           # largos distintos
    assert coseno([1.0, 0.0], [1.0, 0.0]) == 1.0


class ColFalsa:
    """Colección en memoria: entiende solo {"campo": {"$ne": valor}} y $set por _id."""

    name = "articulos"

    def __init__(self, docs):
        self.docs = docs

    def find(self, filtro):
        (campo, cond), = filtro.items()
        return [dict(d) for d in self.docs if d.get(campo) != cond["$ne"]]

    def update_one(self, filtro, cambio):
        next(d for d in self.docs if d["_id"] == filtro["_id"]).update(cambio["$set"])


def test_backfill_etiqueta_lo_compatible_y_revectoriza_lo_demas(monkeypatch):
    from afterdrive.ingesta import embeddings
    monkeypatch.setattr(llm, "modelo_embeddings", lambda: "paga/emb")
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [[9.0, 9.0, 9.0] for _ in textos])
    col = ColFalsa([
        {"_id": 1, "titulo": "legado mismo largo", "embedding": [1.0, 2.0, 3.0]},
        {"_id": 2, "titulo": "legado otro largo", "embedding": [1.0, 2.0]},
        {"_id": 3, "titulo": "otro modelo", "embedding": [1.0, 2.0, 3.0], "embedding_modelo": "nvidia/x"},
        {"_id": 4, "titulo": "sin vector"},
        {"_id": 5, "titulo": "al día", "embedding": [5.0, 5.0, 5.0], "embedding_modelo": "paga/emb"},
    ])
    assert embeddings.backfill([col]) == {"articulos": {"vectorizados": 3, "etiquetados": 1}}
    por_id = {d["_id"]: d for d in col.docs}
    assert por_id[1]["embedding"] == [1.0, 2.0, 3.0]          # solo se etiquetó
    assert all(por_id[i]["embedding"] == [9.0, 9.0, 9.0] for i in (2, 3, 4))
    assert all(d["embedding_modelo"] == "paga/emb" for d in col.docs)
    assert por_id[5]["embedding"] == [5.0, 5.0, 5.0]
    assert embeddings.backfill([col]) == {"articulos": {"vectorizados": 0, "etiquetados": 0}}


def test_backfill_se_cancela_si_la_sonda_falla(monkeypatch):
    from afterdrive.ingesta import embeddings
    monkeypatch.setattr(llm, "modelo_embeddings", lambda: "paga/emb")
    monkeypatch.setattr(llm, "embeber", lambda textos, tipo="passage": [None for _ in textos])
    col = ColFalsa([{"_id": 1, "titulo": "legado", "embedding": [1.0, 2.0]}])
    assert embeddings.backfill([col]) == {}
    assert "embedding_modelo" not in col.docs[0]


def test_chat_con_paga_a_medio_configurar_cae_a_local(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.setenv("PAGA_API_KEY", "pg-key")
    monkeypatch.setenv("PAGA_MODEL", "modelo-pago")
    monkeypatch.delenv("PAGA_BASE_URL", raising=False)
    assert llm._perfil_chat().nombre == "local"
    monkeypatch.setenv("PAGA_BASE_URL", "https://api.paga.test/v1")
    monkeypatch.delenv("PAGA_MODEL")
    assert llm._perfil_chat().nombre == "local"


def test_elegir_paga_para_el_chat_no_cambia_los_embeddings(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "paga")
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)
    for v, x in (("PAGA_API_KEY", "k"), ("PAGA_BASE_URL", "https://api.paga.test/v1"), ("PAGA_EMB_MODEL", "emb")):
        monkeypatch.setenv(v, x)
    monkeypatch.setenv("NVIDIA_API_KEY", "nv")
    monkeypatch.setenv("NVIDIA_EMB_MODEL", "nemotron")
    assert llm.modelo_embeddings() == "nvidia/nemotron"


def test_con_api_paga_clasifica_gpt_y_no_jev(monkeypatch):
    from afterdrive.ingesta import ingesta
    llamados = []
    monkeypatch.setattr(ingesta.jev_clasificador, "clasificar", lambda t, c: llamados.append("jev") or {"aprobado": True})
    monkeypatch.setattr(ingesta.lm_studio, "clasificar_articulo", lambda t, c: llamados.append("gpt") or {"aprobado": True})
    for v, x in (("PAGA_API_KEY", "k"), ("PAGA_BASE_URL", "https://api.paga.test/v1"), ("PAGA_MODEL", "luna")):
        monkeypatch.setenv(v, x)
    monkeypatch.setenv("AI_PROVIDER", "paga")
    ingesta.clasificar("t", "c")
    monkeypatch.setenv("AI_PROVIDER", "nvidia")
    ingesta.clasificar("t", "c")
    assert llamados == ["gpt", "jev"]


def test_atlas_filtra_por_modelo_y_reintenta_sin_filtro(monkeypatch):
    from afterdrive.generacion import contexto_noticias as cn
    monkeypatch.setenv("ATLAS_VECTOR_INDEX", "idx")
    etapas = []

    from pymongo.errors import NetworkTimeout, OperationFailure

    class Col:
        def __init__(self, error):
            self.error = error

        def aggregate(self, pipeline):
            etapas.append(pipeline[0]["$vectorSearch"])
            if "filter" in etapas[-1]:
                raise self.error
            return [{"_id": 1}]

    assert cn._parecidas_en_atlas(Col(OperationFailure("needs to be indexed as filter")), [0.1], "paga/emb") == [{"_id": 1}]
    assert etapas[0]["filter"] == {"embedding_modelo": {"$eq": "paga/emb"}}
    assert "filter" not in etapas[1]
    etapas.clear()
    assert cn._parecidas_en_atlas(Col(NetworkTimeout("timeout")), [0.1], "paga/emb") == []
    assert len(etapas) == 1  # un timeout no se reintenta

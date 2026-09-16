"""Optional search downloads must use the requested immutable model identity."""

import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tfp_client.lib.rag_search import RAGGraph


def test_default_model_download_is_pinned(monkeypatch):
    model = Mock()
    tokenizer = Mock()
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=model, AutoTokenizer=tokenizer))
    graph = RAGGraph()
    graph._load_model()
    for loader in (model, tokenizer):
        revision = loader.from_pretrained.call_args.kwargs["revision"]
        assert re.fullmatch(r"[0-9a-f]{40}", revision)


def test_custom_model_requires_immutable_revision():
    with pytest.raises(ValueError, match="revision"):
        RAGGraph(embedding_model="example/other")
    with pytest.raises(ValueError, match="revision"):
        RAGGraph(embedding_revision="main")


def test_different_model_instances_do_not_reuse_wrong_weights(monkeypatch):
    model = Mock()
    tokenizer = Mock()
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=model, AutoTokenizer=tokenizer))
    first = RAGGraph()
    second = RAGGraph(embedding_model="example/other", embedding_revision="a" * 40)
    first._load_model()
    first._load_model()
    second._load_model()
    assert model.from_pretrained.call_count == 2
    assert model.from_pretrained.call_args.args == ("example/other",)
    assert model.from_pretrained.call_args.kwargs["revision"] == "a" * 40

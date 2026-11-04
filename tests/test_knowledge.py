import pytest

from lilac_chatbot.knowledge import KnowledgeError, create_knowledge_base


def test_a_file_is_uploaded_to_a_new_vector_store(openai_fake, tmp_path):
    faq = tmp_path / "faq.md"
    faq.write_text("# FAQ")
    store = create_knowledge_base(openai_fake.client(), [faq])
    assert store == "vs_demo1" and openai_fake.uploaded == ["faq.md"]
    assert [r.method for r in openai_fake.requests][:3] == ["POST", "POST", "POST"]
    assert len(openai_fake.calls("vector_store_file_poll")) >= 1  # it waited for the indexing


def test_in_memory_files_are_uploaded_by_name(openai_fake):
    create_knowledge_base(openai_fake.client(), [("products.md", b"# Product catalogue")])
    assert openai_fake.uploaded == ["products.md"]


def test_several_files_go_to_the_same_store(openai_fake, tmp_path):
    faq = tmp_path / "faq.md"
    faq.write_text("# FAQ")
    create_knowledge_base(openai_fake.client(), [faq, ("products.md", b"x")])
    assert openai_fake.uploaded == ["faq.md", "products.md"]
    assert len(openai_fake.calls("vector_stores")) == 1


def test_nothing_to_upload_is_an_error(openai_fake):
    with pytest.raises(KnowledgeError, match="nothing"):
        create_knowledge_base(openai_fake.client(), [])
    assert openai_fake.requests == []


def test_a_file_openai_cannot_index_stops_the_job_without_leaking(openai_fake):
    openai_fake.file_status = "failed"
    with pytest.raises(KnowledgeError) as caught:
        create_knowledge_base(openai_fake.client(), [("bad.bin", b"\x00")])
    text = str(caught.value)
    assert "bad.bin" in text and "unsupported_file" in text and "SECRET" not in text


@pytest.mark.parametrize("route", ["vector_stores", "files", "vector_store_files"])
def test_openai_errors_are_reported_by_kind_and_status(openai_fake, route):
    openai_fake.fail[route] = 500
    with pytest.raises(KnowledgeError) as caught:
        create_knowledge_base(openai_fake.client(), [("a.md", b"x")])
    assert "HTTP 500" in str(caught.value) and "SECRET" not in str(caught.value)

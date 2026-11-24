from app.extractor import ExtractResult, Extractor


class FakeFile:
    def __init__(self, state="ACTIVE"):
        self.name = "files/abc123"
        self.uri = "https://files.example/abc123"
        self.state = state


class FakeFiles:
    def __init__(self, state="ACTIVE"):
        self.state = state
        self.uploads = []
        self.deleted = []

    def upload(self, file=None, **kw):
        self.uploads.append(file)
        return FakeFile(self.state)

    def get(self, name=None, **kw):
        return FakeFile(self.state)

    def delete(self, name=None, **kw):
        self.deleted.append(name)


class FakePart:
    def __init__(self, text):
        self.text = text


class FakeContent:
    def __init__(self, text):
        self.parts = [FakePart(text)]


class FakeCandidate:
    def __init__(self, text):
        self.content = FakeContent(text)


class FakeUsage:
    def __init__(self, prompt=5000, output=500, thoughts=0):
        self.prompt_token_count = prompt
        self.candidates_token_count = output
        self.thoughts_token_count = thoughts


class FakeModels:
    def __init__(self, text=None, raises=None, empty_candidates=False, usage=None):
        self.text = text
        self.raises = raises
        self.empty_candidates = empty_candidates
        self.usage = usage
        self.calls = []

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        resp = type("Resp", (), {})()
        resp.candidates = [] if self.empty_candidates else [FakeCandidate(self.text)]
        resp.usage_metadata = self.usage or FakeUsage()
        return resp


class FakeClient:
    def __init__(self, text=None, raises=None, file_state="ACTIVE", empty_candidates=False,
                 usage=None):
        self.files = FakeFiles(file_state)
        self.models = FakeModels(text, raises, empty_candidates, usage)


def test_happy_path_returns_recipe_and_cost():
    fake = FakeClient(text="# Brød\n1. Bland")
    r = Extractor("key", client=fake).extract(b"videobytes", "video/mp4")
    assert isinstance(r, ExtractResult)
    assert r.recipe == "# Brød\n1. Bland"
    assert r.error is None
    assert r.cost_usd > 0
    call = fake.models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert any("NO_RECIPE" in str(c) for c in call["contents"])


def test_sdk_exception_yields_error_result():
    fake = FakeClient(raises=RuntimeError("boom"))
    r = Extractor("key", client=fake).extract(b"v", "video/mp4")
    assert r.recipe is None
    assert r.error


def test_no_recipe_sentinel_yields_no_recipe_error():
    fake = FakeClient(text="NO_RECIPE")
    r = Extractor("key", client=fake).extract(b"v", "video/mp4")
    assert r.recipe is None
    assert r.error == "no_recipe"


def test_failed_file_state_yields_error_result():
    fake = FakeClient(file_state="FAILED")
    r = Extractor("key", client=fake).extract(b"v", "video/mp4")
    assert r.recipe is None
    assert r.error


def test_thoughts_tokens_are_billed_at_output_rate():
    fake = FakeClient(text="# R", usage=FakeUsage(prompt=1_000_000, output=100_000,
                                                  thoughts=400_000))
    r = Extractor("key", client=fake).extract(b"v", "video/mp4")
    import pytest
    assert r.cost_usd == pytest.approx(0.30 + 0.5 * 2.50)


def test_cost_survives_response_parsing_failure():
    """generate_content already spent the money before we parse its shape."""
    fake = FakeClient(empty_candidates=True, usage=FakeUsage(prompt=1000, output=1000))
    r = Extractor("key", client=fake).extract(b"v", "video/mp4")
    assert r.recipe is None
    assert r.error
    assert r.cost_usd > 0

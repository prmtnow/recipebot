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
    def __init__(self, text=None, raises=None, empty_candidates=False, usage=None,
                 raises_first=0):
        self.text = text
        self.raises = raises
        self.empty_candidates = empty_candidates
        self.usage = usage
        self.calls = []
        # raise on the first N generate_content calls, then succeed
        self.raises_first = raises_first

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.raises and (self.raises_first == 0 or len(self.calls) <= self.raises_first):
            raise self.raises
        resp = type("Resp", (), {})()
        resp.candidates = [] if self.empty_candidates else [FakeCandidate(self.text)]
        resp.usage_metadata = self.usage or FakeUsage()
        return resp


class FakeClient:
    def __init__(self, text=None, raises=None, file_state="ACTIVE", empty_candidates=False,
                 usage=None, raises_first=0):
        self.files = FakeFiles(file_state)
        self.models = FakeModels(text, raises, empty_candidates, usage, raises_first)


def test_happy_path_returns_recipe_and_cost():
    fake = FakeClient(text="# Brød\n1. Bland")
    r = Extractor("key", client=fake).extract(b"videobytes", "video/mp4")
    assert isinstance(r, ExtractResult)
    assert r.recipe == "# Brød\n1. Bland"
    assert r.error is None
    assert r.cost_usd > 0
    call = fake.models.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert any("NO_RECIPE" in str(c) for c in call["contents"])


def test_model_is_configurable():
    fake = FakeClient(text="# R")
    Extractor("key", client=fake, model="gemini-3.5-flash").extract(b"v", "video/mp4")
    assert fake.models.calls[0]["model"] == "gemini-3.5-flash"


def test_transient_error_is_retried_then_succeeds():
    fake = FakeClient(text="# R", raises=RuntimeError("503 UNAVAILABLE high demand"),
                      raises_first=1)
    slept = []
    r = Extractor("key", client=fake, sleep=slept.append).extract(b"v", "video/mp4")
    assert r.recipe == "# R"
    assert r.error is None
    assert len(fake.models.calls) == 2
    assert slept == [10]


def test_persistent_transient_error_gives_up_after_three_attempts():
    fake = FakeClient(raises=RuntimeError("503 UNAVAILABLE"), raises_first=0)
    slept = []
    r = Extractor("key", client=fake, sleep=slept.append).extract(b"v", "video/mp4")
    assert r.recipe is None
    assert "503" in r.error
    assert len(fake.models.calls) == 3
    assert slept == [10, 20]


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

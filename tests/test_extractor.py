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

    def upload(self, file=None, **kw):
        self.uploads.append(file)
        return FakeFile(self.state)

    def get(self, name=None, **kw):
        return FakeFile(self.state)


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
    prompt_token_count = 5000
    candidates_token_count = 500


class FakeModels:
    def __init__(self, text=None, raises=None):
        self.text = text
        self.raises = raises
        self.calls = []

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        resp = type("Resp", (), {})()
        resp.candidates = [FakeCandidate(self.text)]
        resp.usage_metadata = FakeUsage()
        return resp


class FakeClient:
    def __init__(self, text=None, raises=None, file_state="ACTIVE"):
        self.files = FakeFiles(file_state)
        self.models = FakeModels(text, raises)


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

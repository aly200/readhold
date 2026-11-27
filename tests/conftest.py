import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def no_real_secrets_or_servers(monkeypatch):
    """No test touches the real credential store, and no test can reach a real server:
    keys go to a store in memory, and a real HTTP transport fails the test (AI tests use a mock transport)."""
    import httpx
    import keyring
    import keyring.backend
    import keyring.errors

    from readhold import redact

    class MemoryKeyring(keyring.backend.KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.store = {}

        def get_password(self, service, username):
            return self.store.get((service, username))

        def set_password(self, service, username, password):
            self.store[(service, username)] = password

        def delete_password(self, service, username):
            if (service, username) not in self.store:
                raise keyring.errors.PasswordDeleteError("not found")
            del self.store[(service, username)]

    async def refuse_async(self, request):
        raise AssertionError(f"a test tried to reach a real server: {request.url}")

    def refuse(self, request):
        raise AssertionError(f"a test tried to reach a real server: {request.url}")

    before = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    redact.forget_all()
    yield
    redact.forget_all()
    keyring.set_keyring(before)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("READHOLD_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def db(home):
    from readhold.db import open_db

    return open_db()


@pytest.fixture()
def client(db):
    from readhold.server import create_app

    app = create_app(db, TOKEN, {"testserver"})
    c = TestClient(app)
    r = c.get(f"/auth?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    return c


SAMPLE_MD = """# Attention Is a Test

## Abstract

We propose the Sparse Mixture Router (SMR), a routing layer for transformers. SMR reduces compute by 41% on long inputs. Our results show it matches dense models.

## Introduction

Long documents are hard for transformers. Attention cost grows with the square of the length. We define a router as a module that picks which tokens attend.

## Related Work

Prior work studied sparse attention [12]. Others used memory tokens [3].

## Method

The SMR is a gating network over token blocks. Each block gets a score, and the top-k blocks are kept. `top-k` routing is cheap.

```python
def route(x): return x
```

## Results

On the LongBench suite, SMR scores 71.2 versus 70.8 for the dense baseline. See Figure 2 for the curves.

## References

[3] A. Author. Memory tokens. 2020.
[12] B. Author. Sparse attention. 2019.
"""


@pytest.fixture()
def sample_md():
    return SAMPLE_MD

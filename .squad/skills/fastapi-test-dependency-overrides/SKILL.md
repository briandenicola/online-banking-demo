# Skill: FastAPI Test Dependency Overrides

## When to Use This Pattern

When writing pytest fixtures for FastAPI applications that use the `Depends()` pattern for dependency injection.

## The Pattern

FastAPI routes declare dependencies via `Depends()`:

```python
# app/dependencies.py
async def get_repository(request: Request) -> ApplicationRepository:
    return request.app.state.repository

# app/routes/api.py
@router.post("/applications")
async def create_application(
    payload: ApplicationCreate,
    repository: ApplicationRepository = Depends(get_repository),
):
    application = repository.create(payload)
    return application
```

To test these routes, override dependencies in your pytest fixture using **async functions**:

```python
# tests/conftest.py
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

@pytest_asyncio.fixture
async def app_client(mock_redis):
    """httpx.AsyncClient wired to the FastAPI app (no real server)."""
    from app.main import app
    from app.dependencies import get_repository, get_redis_client
    from app.repository import InMemoryApplicationRepository

    # Create test instances
    repository = InMemoryApplicationRepository()
    
    # Define async override functions
    async def override_repository():
        return repository
    
    async def override_redis():
        return mock_redis
    
    # Register overrides
    app.dependency_overrides[get_repository] = override_repository
    app.dependency_overrides[get_redis_client] = override_redis

    # Create test client
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    # Clean up after tests
    app.dependency_overrides.clear()
```

## Common Mistakes

### ❌ Using sync lambda functions

```python
# WRONG — will cause asyncio Task assertion errors
app.dependency_overrides[get_repository] = lambda: repository
```

**Why this fails:** FastAPI's dependency resolver expects async callables when the original dependency is async. Sync lambdas cause type mismatches in the asyncio event loop.

### ❌ Returning coroutines instead of values

```python
# WRONG — will cause "coroutine not awaited" errors
async def override_repository():
    return await some_async_call()  # OK if needed
    return repository()  # BAD if repository() is sync

# CORRECT
async def override_repository():
    return repository  # Just return the value
```

## When Async Overrides Are Required

- Original dependency function is `async def`
- Dependency is registered with `Depends(async_function)`
- App uses async context managers or lifespan events

## When Sync Overrides Might Work

Only when **all** of these are true:
- Original dependency is `def` (not `async def`)
- No async context in the dependency chain
- App runs in sync mode (rare for FastAPI)

**Rule of thumb:** Always use async override functions for FastAPI apps. It's safer and forward-compatible.

## Testing Multiple Dependencies

Override all dependencies your routes need:

```python
async def override_repo():
    return mock_repo

async def override_redis():
    return mock_redis

async def override_blob_client():
    return None  # Or mock blob client

async def override_state_machine():
    return ApplicationStateMachine()

app.dependency_overrides[get_repository] = override_repo
app.dependency_overrides[get_redis_client] = override_redis
app.dependency_overrides[get_blob_service_client] = override_blob_client
app.dependency_overrides[get_state_machine] = override_state_machine
```

## Debugging Override Issues

If tests fail with errors like:
- `AssertionError: assert False` in `anyio._backends._asyncio`
- `TypeError: object is not callable`
- `AttributeError: 'coroutine' object has no attribute 'X'`

Check:
1. Are your overrides async functions?
2. Do they return values (not coroutines)?
3. Is `dependency_overrides.clear()` called in fixture cleanup?

## Project History

This pattern was established during issue #115 (Python test repairs after Wave 1 service extraction). All 4 Python services (ai, budget, chatbot, account-opening) use this pattern as of 2026-05-13.

## References

- FastAPI docs: [Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
- Issue #115: Repair Python service tests after Wave 1 #93 extraction
- Commits: 002e24b (ai), 3481962 (budget), c7435e8 (chatbot), e4fc3b4 (account-opening)

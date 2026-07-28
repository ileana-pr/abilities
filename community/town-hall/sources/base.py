import json
from abc import ABC, abstractmethod
from typing import Any, Optional


class _HttpResp:
    """normalize session_tasks http results into a requests-like object."""

    def __init__(self, status_code: int, text: str, parsed: Optional[dict] = None):
        self.status_code = int(status_code)
        self.text = text if text is not None else ""
        self._parsed = parsed

    def json(self):
        if self._parsed is not None:
            return self._parsed
        if not self.text:
            return {}
        return json.loads(self.text)


class CivicSource(ABC):
    """Base class for all civic data sources (Cities, Counties, States)."""

    def __init__(self):
        self._worker = None
        self._api_key: Optional[str] = None

    def bind_worker(self, worker: Any) -> None:
        """attach openhome worker so sources can use session_tasks http helpers."""
        self._worker = worker

    def required_api_key_name(self) -> Optional[str]:
        """override to declare the third-party key name this source needs.
        return None if no api key is required."""
        return None

    def set_api_key(self, api_key: Optional[str]) -> None:
        """called by the capability coordinator after resolving required_api_key_name."""
        self._api_key = api_key.strip() if api_key else None

    def trigger_keywords(self) -> tuple[str, ...]:
        """override to declare which keywords in the trigger phrase activate this source.
        return an empty tuple to always include this source regardless of trigger."""
        return ()

    def validate_cache(self, content: str) -> bool:
        """return False if this source's section in the aggregated briefing looks errored.
        the coordinator uses this to decide whether to serve or discard a cached briefing."""
        name = self.get_name()
        marker = f"### {name}"
        if marker not in content:
            return True
        start = content.index(marker)
        end = content.find("---", start)
        section = content[start:end] if end != -1 else content[start:]
        data_lines = [
            l.strip() for l in section.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        if not data_lines:
            return False
        return not all(
            l.lower().startswith("- error") or l.lower().startswith("error")
            for l in data_lines
        )

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def get_source_url(self) -> str:
        pass

    @abstractmethod
    async def fetch_updates(self) -> str:
        pass

    async def search(self, query: str) -> str:
        return f"Live search not yet implemented for {self.get_name()}."

    async def get_details(self, item_id: str) -> str:
        return f"Detail retrieval not yet implemented for {self.get_name()}."

    def get_metadata(self) -> dict:
        return {}

    def _is_response_like(self, obj: Any) -> bool:
        """true for session_tasks Response objects (sync; must not be awaited)."""
        try:
            _ = obj.status_code
            return True
        except Exception:
            return False

    def _is_coroutine_type(self, obj: Any) -> bool:
        # only trust the type name — do not duck-type send/close (Response may have close)
        name = type(obj).__name__
        return name in ("coroutine", "Coroutine", "Task", "Future")

    def _wrap_http_result(self, raw: Any) -> _HttpResp:
        if raw is None:
            return _HttpResp(502, "")

        if self._is_response_like(raw):
            text = ""
            try:
                text = raw.text
            except Exception:
                text = ""
            if text is None:
                text = ""
            if not text:
                try:
                    content = raw.content
                    if isinstance(content, (bytes, bytearray)):
                        text = content.decode("utf-8", errors="replace")
                    elif content is not None:
                        text = str(content)
                except Exception:
                    text = ""
            if not isinstance(text, str):
                text = str(text)
            return _HttpResp(int(raw.status_code), text)

        if isinstance(raw, dict):
            if "status_code" in raw or "status" in raw or "text" in raw or "body" in raw:
                text = raw.get("text") or raw.get("body") or raw.get("content") or ""
                if not isinstance(text, str):
                    text = json.dumps(text)
                status = raw.get("status_code") or raw.get("status") or 200
                parsed = raw.get("json") if isinstance(raw.get("json"), dict) else None
                return _HttpResp(int(status), text, parsed)
            return _HttpResp(200, "", parsed=raw)

        if isinstance(raw, (bytes, bytearray)):
            return _HttpResp(200, raw.decode("utf-8", errors="replace"))

        if isinstance(raw, str):
            return _HttpResp(200, raw)

        return _HttpResp(200, str(raw))

    async def _resolve_get_result(self, result: Any) -> Any:
        """unwrap at most one coroutine; never await a Response object."""
        # IMPORTANT: check Response before coroutine. Response.close() must not
        # make us treat it as awaitable.
        if self._is_response_like(result):
            return result
        if isinstance(result, (str, bytes, bytearray, dict, list, int, float, _HttpResp)):
            return result
        if self._is_coroutine_type(result):
            unwrapped = await result
            # platform may mistakenly return something still awaitable; stop if Response
            if self._is_response_like(unwrapped):
                return unwrapped
            return unwrapped
        return result

    async def _http_get(self, url: str, headers: Optional[dict] = None, timeout: float = 30):
        if self._worker is None:
            raise RuntimeError("HTTP worker not bound — call bind_worker() first")

        result = None
        err = None
        # prefer headers when provided (range requests, api keys)
        if headers:
            try:
                result = self._worker.session_tasks.get(url, headers)
                err = None
            except TypeError as e:
                err = e
                try:
                    result = self._worker.session_tasks.get(url, headers=headers)
                    err = None
                except TypeError:
                    try:
                        result = self._worker.session_tasks.get(url)
                        err = None
                    except Exception as e2:
                        err = e2
                except Exception as e2:
                    err = e2
            except Exception as e:
                err = e
        else:
            try:
                result = self._worker.session_tasks.get(url)
            except Exception as e:
                err = e

        if err is not None and result is None:
            raise RuntimeError(f"session_tasks.get failed: {err}")

        raw = await self._resolve_get_result(result)

        try:
            preview = f"type={type(raw).__name__}"
            if self._is_response_like(raw):
                preview = f"Response status={raw.status_code}"
            elif isinstance(raw, str):
                preview = raw[:60].replace("\n", " ")
            self._worker.editor_logging_handler.info(
                f"http get {preview} url={url[:90]}"
            )
        except Exception:
            pass

        return self._wrap_http_result(raw)

    async def _http_post(
        self,
        url: str,
        headers: Optional[dict] = None,
        json_body: Optional[dict] = None,
        timeout: float = 30,
    ):
        if self._worker is None:
            raise RuntimeError("HTTP worker not bound — call bind_worker() first")
        try:
            result = self._worker.session_tasks.post(url, headers or {}, json_body or {})
        except TypeError:
            result = self._worker.session_tasks.post(url)
        raw = await self._resolve_get_result(result)
        return self._wrap_http_result(raw)

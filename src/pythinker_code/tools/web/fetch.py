import ipaddress
import socket
from pathlib import Path
from typing import override
from urllib.parse import urljoin, urlparse

import aiohttp
import trafilatura
from pydantic import BaseModel, Field
from pythinker_core.tooling import CallableTool2, ToolReturnValue

from pythinker_code.config import Config
from pythinker_code.constant import USER_AGENT
from pythinker_code.execution_profiles import resolve_execution_policy
from pythinker_code.soul.agent import Runtime
from pythinker_code.soul.toolset import get_current_tool_call_or_none
from pythinker_code.tools.utils import ToolResultBuilder, load_desc
from pythinker_code.utils.aiohttp import new_client_session
from pythinker_code.utils.logging import logger

MAX_FETCH_BYTES = 5 * 1024 * 1024
MAX_FETCH_REDIRECTS = 10  # matches aiohttp's default redirect cap
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _validate_fetch_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "Only http and https URLs are supported."
    if not parsed.hostname:
        return "URL must include a host."

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return (
                "Fetching private, local, link-local, multicast, or reserved addresses is blocked."
            )
    return None


async def _read_limited(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    length = response.headers.get(aiohttp.hdrs.CONTENT_LENGTH)
    if length is not None:
        try:
            if int(length) > max_bytes:
                raise ValueError("response too large")
        except ValueError as exc:
            raise ValueError("response too large") from exc

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("response too large")
        chunks.append(chunk)
    return b"".join(chunks)


class _FetchBlocked(Exception):
    """Raised when a URL or one of its redirect targets fails SSRF validation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _get_revalidating_redirects(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str]
) -> aiohttp.ClientResponse:
    """GET ``url``, following redirects manually and re-validating every hop.

    aiohttp follows redirects internally without re-checking the destination, so
    a public URL that 30x-redirects to a private/link-local address (e.g. a cloud
    metadata endpoint at 169.254.169.254) would otherwise sail past
    ``_validate_fetch_url``. We disable automatic redirects and validate each
    ``Location`` before following it.

    Returns the final, open, non-redirect response (the caller owns closing it).
    Raises ``_FetchBlocked`` if any hop is blocked or the redirect limit is hit.
    """
    current = url
    for _ in range(MAX_FETCH_REDIRECTS + 1):
        if reason := _validate_fetch_url(current):
            raise _FetchBlocked(reason)
        response = await session.get(current, headers=headers, allow_redirects=False)
        location = response.headers.get(aiohttp.hdrs.LOCATION)
        if response.status in _REDIRECT_STATUSES and location:
            response.release()
            current = urljoin(str(response.url), location)
            continue
        return response
    raise _FetchBlocked("too many redirects")


class Params(BaseModel):
    url: str = Field(description="The URL to fetch content from.")


class FetchURL(CallableTool2[Params]):
    name: str = "FetchURL"
    description: str = load_desc(Path(__file__).parent / "fetch.md", {})
    params: type[Params] = Params

    def __init__(self, config: Config, runtime: Runtime):
        super().__init__()
        self._runtime = runtime
        self._service_config = config.services.pythinker_ai_fetch

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        policy = resolve_execution_policy(
            self._runtime.config.agent_execution_profile,
            yolo=self._runtime.approval.is_yolo_flag(),
        )
        if policy.network == "deny":
            return ToolResultBuilder().error(
                "Network fetch is denied by the active execution profile.",
                brief="Execution profile restriction",
            )
        if self._service_config:
            ret = await self._fetch_with_service(params)
            if not ret.is_error:
                return ret
            logger.warning("Failed to fetch URL via service: {error}", error=ret.message)
            # fallback to local fetch if service fetch fails
        return await self.fetch_with_http_get(params)

    @staticmethod
    async def fetch_with_http_get(params: Params) -> ToolReturnValue:
        builder = ToolResultBuilder(max_line_length=None)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }
        try:
            # Fetching arbitrary web pages can take a while on large/slow sites.
            fetch_timeout = aiohttp.ClientTimeout(total=180, sock_read=60, sock_connect=15)
            async with new_client_session(timeout=fetch_timeout) as session:
                try:
                    response = await _get_revalidating_redirects(session, params.url, headers)
                except _FetchBlocked as blocked:
                    return builder.error(
                        f"Failed to fetch URL: {blocked.reason}", brief="URL blocked"
                    )
                async with response:
                    if response.status >= 400:
                        logger.warning(
                            "FetchURL HTTP error: status={status}, url={url}",
                            status=response.status,
                            url=params.url,
                        )
                        return builder.error(
                            (
                                f"Failed to fetch URL. Status: {response.status}. "
                                "This may indicate the page is not accessible or "
                                "the server is down."
                            ),
                            brief=f"HTTP {response.status} error",
                        )

                    try:
                        resp_text = (await _read_limited(response, MAX_FETCH_BYTES)).decode(
                            "utf-8", errors="replace"
                        )
                    except ValueError:
                        max_mb = MAX_FETCH_BYTES // 1024 // 1024
                        return builder.error(
                            f"Failed to fetch URL: response exceeds {max_mb}MB.",
                            brief="Response too large",
                        )

                    content_type = response.headers.get(aiohttp.hdrs.CONTENT_TYPE, "").lower()
                    if content_type.startswith(("text/plain", "text/markdown")):
                        builder.write(resp_text)
                        return builder.ok("The returned content is the full content of the page.")
        except TimeoutError:
            logger.warning("FetchURL timed out: url={url}", url=params.url)
            return builder.error(
                "Failed to fetch URL: request timed out. The server may be slow or unreachable.",
                brief="Request timed out",
            )
        except aiohttp.ClientError as e:
            logger.warning("FetchURL network error: {error}, url={url}", error=e, url=params.url)
            return builder.error(
                (
                    f"Failed to fetch URL due to network error: {e}. "
                    "This may indicate the URL is invalid or the server is unreachable."
                ),
                brief="Network error",
            )

        if not resp_text:
            return builder.ok(
                "The response body is empty.",
                brief="Empty response body",
            )

        extracted_text = trafilatura.extract(
            resp_text,
            include_comments=True,
            include_tables=True,
            include_formatting=False,
            output_format="txt",
            with_metadata=True,
        )

        if not extracted_text:
            return builder.error(
                (
                    "Failed to extract meaningful content from the page. "
                    "This may indicate the page content is not suitable for text extraction, "
                    "or the page requires JavaScript to render its content."
                ),
                brief="No content extracted",
            )

        builder.write(extracted_text)
        return builder.ok("The returned content is the main text content extracted from the page.")

    async def _fetch_with_service(self, params: Params) -> ToolReturnValue:
        assert self._service_config is not None

        tool_call = get_current_tool_call_or_none()
        assert tool_call is not None, "Tool call is expected to be set"

        builder = ToolResultBuilder(max_line_length=None)
        api_key = self._runtime.oauth.resolve_api_key(
            self._service_config.api_key, self._service_config.oauth
        )
        if not api_key:
            return builder.error(
                "Fetch service is not configured. You may want to try other methods to fetch.",
                brief="Fetch service not configured",
            )
        if reason := _validate_fetch_url(params.url):
            return builder.error(f"Failed to fetch URL: {reason}", brief="URL blocked")

        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {api_key}",
            "Accept": "text/markdown",
            "X-Msh-Tool-Call-Id": tool_call.id,
            **self._runtime.oauth.common_headers(),
            **(self._service_config.custom_headers or {}),
        }

        try:
            async with (
                new_client_session() as session,
                session.post(
                    self._service_config.base_url,
                    headers=headers,
                    json={"url": params.url},
                ) as response,
            ):
                if response.status != 200:
                    logger.warning(
                        "FetchURL service HTTP error: status={status}, url={url}",
                        status=response.status,
                        url=params.url,
                    )
                    return builder.error(
                        f"Failed to fetch URL via service. Status: {response.status}.",
                        brief="Failed to fetch URL via fetch service",
                    )

                try:
                    content = (await _read_limited(response, MAX_FETCH_BYTES)).decode(
                        "utf-8", errors="replace"
                    )
                except ValueError:
                    max_mb = MAX_FETCH_BYTES // 1024 // 1024
                    return builder.error(
                        f"Failed to fetch URL via service: response exceeds {max_mb}MB.",
                        brief="Response too large",
                    )
                builder.write(content)
                return builder.ok(
                    "The returned content is the main content extracted from the page."
                )
        except TimeoutError:
            logger.warning("FetchURL service timed out: url={url}", url=params.url)
            return builder.error(
                "Failed to fetch URL via service: request timed out.",
                brief="Service request timed out",
            )
        except aiohttp.ClientError as e:
            logger.warning(
                "FetchURL service network error: {error}, url={url}", error=e, url=params.url
            )
            return builder.error(
                (
                    f"Failed to fetch URL via service due to network error: {e}. "
                    "This may indicate the service is unreachable."
                ),
                brief="Network error when calling fetch service",
            )

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from camoufox_mcp.tools._base import get_page, get_session, tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from camoufox_mcp.tools._base import ToolDeps

# W3C Navigation Timing (Level 2) + Resource Timing collected in-page. No CDP.
_PERF_JS = """
(() => {
  const nav = performance.getEntriesByType('navigation')[0] || null;
  const timings = nav ? {
    dns: nav.domainLookupEnd - nav.domainLookupStart,
    tcp: nav.connectEnd - nav.connectStart,
    tls: nav.secureConnectionStart > 0 ? nav.connectEnd - nav.secureConnectionStart : 0,
    ttfb: nav.responseStart - nav.requestStart,
    response: nav.responseEnd - nav.responseStart,
    domInteractive: nav.domInteractive - nav.startTime,
    domContentLoaded: nav.domContentLoadedEventEnd - nav.startTime,
    domComplete: nav.domComplete - nav.startTime,
    loadEvent: nav.loadEventEnd - nav.startTime,
    transferSize: nav.transferSize || 0
  } : null;
  const paints = {};
  for (const p of performance.getEntriesByType('paint')) {
    paints[p.name] = p.startTime;
  }
  const resources = performance.getEntriesByType('resource');
  const byType = {};
  let totalTransfer = 0;
  for (const r of resources) {
    const t = r.initiatorType || 'other';
    if (!byType[t]) byType[t] = { count: 0, transferSize: 0 };
    byType[t].count += 1;
    byType[t].transferSize += (r.transferSize || 0);
    totalTransfer += (r.transferSize || 0);
  }
  return {
    url: location.href,
    timings: timings,
    paints: paints,
    resourceCount: resources.length,
    totalTransferSize: totalTransfer,
    byType: byType
  };
})()
"""


def register(mcp: FastMCP, deps: ToolDeps) -> None:
    @tool(mcp, deps)
    async def performance_summary(profile: str) -> str:
        """Summarize page performance from W3C Navigation & Resource Timing APIs.

        Reads the browser's own ``performance`` timeline on the active tab (no CDP
        tracing) and returns a human-readable summary: key navigation phase timings
        (DNS, TCP, TLS, TTFB, DOM milestones, load event), First Paint /
        First Contentful Paint when available, the total number of loaded resources,
        their combined transfer size, and a breakdown of resource count and transfer
        size by initiator type (script, css, img, fetch, xmlhttprequest, ...).

        Params:
        - profile: session/profile name (required). The session is created lazily.

        Returns a formatted text report. If no navigation entry exists yet (e.g. the
        page has not been navigated), navigation timings are reported as
        unavailable while resource stats are still shown.

        Errors: "Error: ProfileInUseError: ..." if the profile is locked;
        "Error: RuntimeError: ..." if there is no active page.
        """
        session = await get_session(deps, profile)
        page = get_page(session)
        data: dict[str, Any] = await page.evaluate(_PERF_JS)
        return _format(data)


def _ms(value: Any) -> str:
    try:
        return f"{float(value):.1f} ms"
    except (TypeError, ValueError):
        return "n/a"


def _kb(num_bytes: Any) -> str:
    try:
        return f"{float(num_bytes) / 1024:.1f} KB"
    except (TypeError, ValueError):
        return "n/a"


def _format(data: dict[str, Any]) -> str:
    lines = [f"Performance summary for {data.get('url', '<unknown>')}", ""]

    timings = data.get("timings")
    lines.append("Navigation timings:")
    if timings:
        rows = [
            ("DNS lookup", "dns"),
            ("TCP connect", "tcp"),
            ("TLS handshake", "tls"),
            ("Time to first byte", "ttfb"),
            ("Response download", "response"),
            ("DOM interactive", "domInteractive"),
            ("DOMContentLoaded", "domContentLoaded"),
            ("DOM complete", "domComplete"),
            ("Load event end", "loadEvent"),
        ]
        for label, key in rows:
            lines.append(f"  {label}: {_ms(timings.get(key))}")
        lines.append(f"  Document transfer size: {_kb(timings.get('transferSize'))}")
    else:
        lines.append("  <no navigation entry available>")

    paints = data.get("paints") or {}
    if paints:
        lines += ["", "Paint timings:"]
        for name in ("first-paint", "first-contentful-paint"):
            if name in paints:
                lines.append(f"  {name}: {_ms(paints[name])}")

    lines += [
        "",
        f"Resources loaded: {data.get('resourceCount', 0)}",
        f"Total transfer size: {_kb(data.get('totalTransferSize'))}",
    ]

    by_type = data.get("byType") or {}
    if by_type:
        lines.append("Breakdown by initiator type:")
        for t in sorted(by_type):
            info = by_type[t]
            lines.append(f"  {t}: {info.get('count', 0)} req, {_kb(info.get('transferSize'))}")

    return "\n".join(lines)

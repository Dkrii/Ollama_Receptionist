import argparse
import csv
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class RunResult:
    query_id: str
    category: str
    message: str
    endpoint: str
    status: str
    handled: bool
    http_status: int
    ttft_ms: float
    total_ms: float
    answer_chars: int
    contact_probe_called: bool

def post_stream(
    url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, float, float, str, str | None, dict[str, Any], str]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})

    started = time.perf_counter()
    first_token_ms: float | None = None
    answer_parts: list[str] = []
    conversation_id: str | None = None
    flow_state: dict[str, Any] = {"stage": "idle"}
    route = "rag"

    with urlopen(req, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "meta":
                conversation_id = event.get("conversation_id") or conversation_id
                if isinstance(event.get("flow_state"), dict):
                    flow_state = event["flow_state"]
                route = str(event.get("route") or route)
            elif event.get("type") == "token":
                token = str(event.get("value") or "")
                if token and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - started) * 1000
                answer_parts.append(token)

        total_ms = (time.perf_counter() - started) * 1000

    return (
        200,
        float(first_token_ms or total_ms),
        float(total_ms),
        "".join(answer_parts).strip(),
        conversation_id,
        flow_state,
        route,
    )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def run_benchmark(base_url: str, testset_path: Path, timeout: float) -> dict[str, Any]:
    testset = json.loads(testset_path.read_text(encoding="utf-8"))

    flow_state: dict[str, Any] = {"stage": "idle"}
    conversation_id: str | None = None
    results: list[RunResult] = []

    for item in testset:
        query_id = str(item.get("id") or "")
        category = str(item.get("category") or "")
        message = str(item.get("message") or "").strip()

        if not message:
            continue

        try:
            status, ttft_ms, total_ms, answer_text, next_conversation_id, next_flow_state, route = post_stream(
                f"{base_url}/api/chat/stream",
                {
                    "message": message,
                    "conversation_id": conversation_id,
                    "history": [],
                    "flow_state": flow_state,
                },
                timeout=timeout,
            )
            conversation_id = next_conversation_id or conversation_id
            flow_state = next_flow_state if isinstance(next_flow_state, dict) else {"stage": "idle"}
            handled = route == "contact_flow"
            endpoint = "contact-flow" if handled else "chat-stream"

            results.append(
                RunResult(
                    query_id=query_id,
                    category=category,
                    message=message,
                    endpoint=endpoint,
                    status="ok",
                    handled=handled,
                    http_status=status,
                    ttft_ms=ttft_ms,
                    total_ms=total_ms,
                    answer_chars=len(answer_text),
                    contact_probe_called=False,
                )
            )
        except HTTPError as exc:
            results.append(
                RunResult(
                    query_id=query_id,
                    category=category,
                    message=message,
                    endpoint="chat-stream",
                    status=f"http_error:{exc.code}",
                    handled=False,
                    http_status=int(exc.code),
                    ttft_ms=0.0,
                    total_ms=0.0,
                    answer_chars=0,
                    contact_probe_called=False,
                )
            )
        except URLError:
            results.append(
                RunResult(
                    query_id=query_id,
                    category=category,
                    message=message,
                    endpoint="chat-stream",
                    status="connection_error",
                    handled=False,
                    http_status=0,
                    ttft_ms=0.0,
                    total_ms=0.0,
                    answer_chars=0,
                    contact_probe_called=False,
                )
            )

    success = [row for row in results if row.status == "ok"]
    ttft_values = [row.ttft_ms for row in success if row.ttft_ms > 0]
    total_values = [row.total_ms for row in success if row.total_ms > 0]

    summary = {
        "total_queries": len(results),
        "ok_queries": len(success),
        "error_queries": len(results) - len(success),
        "ttft_ms_p50": round(percentile(ttft_values, 0.5), 2),
        "ttft_ms_p95": round(percentile(ttft_values, 0.95), 2),
        "total_ms_p50": round(percentile(total_values, 0.5), 2),
        "total_ms_p95": round(percentile(total_values, 0.95), 2),
        "total_ms_avg": round(statistics.mean(total_values), 2) if total_values else 0.0,
        "contact_probe_called": sum(1 for row in results if row.contact_probe_called),
        "contact_flow_handled": sum(1 for row in results if row.endpoint == "contact-flow" and row.handled),
    }

    return {
        "summary": summary,
        "rows": [row.__dict__ for row in results],
    }


def write_outputs(payload: dict[str, Any], output_dir: Path, tag: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"benchmark-{tag}.json"
    csv_path = output_dir / f"benchmark-{tag}.csv"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = payload.get("rows") or []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "query_id",
            "category",
            "message",
            "endpoint",
            "status",
            "handled",
            "http_status",
            "ttft_ms",
            "total_ms",
            "answer_chars",
            "contact_probe_called",
        ])
        writer.writeheader()
        writer.writerows(rows)

    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 10-query benchmark against chat API and export before/after metrics.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--testset", default="qa/testset-10.json")
    parser.add_argument("--output-dir", default="qa/results")
    parser.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    payload = run_benchmark(
        base_url=args.base_url.rstrip("/"),
        testset_path=Path(args.testset),
        timeout=float(args.timeout),
    )
    json_path, csv_path = write_outputs(payload, Path(args.output_dir), str(args.tag))

    print(json.dumps({
        "summary": payload["summary"],
        "json": str(json_path),
        "csv": str(csv_path),
    }, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

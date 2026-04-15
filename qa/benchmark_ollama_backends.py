import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def measure_generate(
    base_url: str,
    model: str,
    prompt: str,
    runs: int,
    timeout: float,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "num_predict": 64,
            "num_ctx": 2048,
            "num_thread": 8,
        },
    }

    for index in range(runs):
        started = time.perf_counter()
        response = post_json(f"{base_url}/api/generate", payload, timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000
        samples.append(
            {
                "run": index + 1,
                "elapsed_ms": round(elapsed_ms, 2),
                "total_duration_ms": round(float(response.get("total_duration") or 0) / 1_000_000, 2),
                "load_duration_ms": round(float(response.get("load_duration") or 0) / 1_000_000, 2),
                "prompt_eval_count": int(response.get("prompt_eval_count") or 0),
                "eval_count": int(response.get("eval_count") or 0),
                "response_chars": len(str(response.get("response") or "")),
            }
        )

    elapsed_values = [sample["elapsed_ms"] for sample in samples]
    return {
        "runs": samples,
        "avg_elapsed_ms": round(statistics.mean(elapsed_values), 2),
        "min_elapsed_ms": round(min(elapsed_values), 2),
        "max_elapsed_ms": round(max(elapsed_values), 2),
    }


def measure_embed(
    base_url: str,
    model: str,
    text: str,
    runs: int,
    timeout: float,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    payload = {
        "model": model,
        "input": [text],
    }

    for index in range(runs):
        started = time.perf_counter()
        response = post_json(f"{base_url}/api/embed", payload, timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000
        embeddings = response.get("embeddings") or []
        vector_size = len(embeddings[0]) if embeddings and isinstance(embeddings[0], list) else 0
        samples.append(
            {
                "run": index + 1,
                "elapsed_ms": round(elapsed_ms, 2),
                "total_duration_ms": round(float(response.get("total_duration") or 0) / 1_000_000, 2),
                "load_duration_ms": round(float(response.get("load_duration") or 0) / 1_000_000, 2),
                "prompt_eval_count": int(response.get("prompt_eval_count") or 0),
                "vector_size": vector_size,
            }
        )

    elapsed_values = [sample["elapsed_ms"] for sample in samples]
    return {
        "runs": samples,
        "avg_elapsed_ms": round(statistics.mean(elapsed_values), 2),
        "min_elapsed_ms": round(min(elapsed_values), 2),
        "max_elapsed_ms": round(max(elapsed_values), 2),
    }


def build_cases() -> dict[str, dict[str, str]]:
    rag_context = (
        "Konteks perusahaan: kantor buka Senin sampai Jumat pukul 08.00 sampai 17.00. "
        "Layanan resepsionis membantu tamu mencari divisi, fasilitas, dan prosedur kunjungan. "
        "Mushola berada di lantai 2 dekat pantry. Klinik tersedia di lantai dasar sebelah ruang keamanan. "
        "Titik kumpul darurat berada di halaman depan dekat pos satpam. "
        "Area parkir tamu berada di sisi timur gedung dan wajib registrasi di resepsionis. "
        "Visitor yang ingin bertemu karyawan akan dikonfirmasi terlebih dahulu sebelum diarahkan ke lobby. "
        "Jika target tidak tersedia, resepsionis menawarkan menitip pesan atau menunggu di area lobby. "
        "Perusahaan menjaga sopan santun, jawaban singkat, dan instruksi yang mudah diikuti. "
        "Pengetahuan ini dipakai untuk menjawab pertanyaan umum pengunjung dengan ringkas dan jelas. "
        "Pertanyaan: jelaskan jam operasional kantor dan sampaikan lokasi mushola dalam jawaban singkat."
    )

    return {
        "chat_short": {
            "type": "generate",
            "prompt": "Pengunjung bertanya: kantor buka jam berapa pada hari kerja?",
        },
        "chat_rag_like": {
            "type": "generate",
            "prompt": rag_context,
        },
        "embed_query": {
            "type": "embed",
            "prompt": "tolong carikan informasi jam operasional kantor hari kerja",
        },
    }


def compare_backend_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    gpu_results = payload["backends"]["gpu"]["cases"]
    cpu_results = payload["backends"]["cpu"]["cases"]

    for case_name in gpu_results:
        gpu_avg = float(gpu_results[case_name]["avg_elapsed_ms"])
        cpu_avg = float(cpu_results[case_name]["avg_elapsed_ms"])
        comparison[case_name] = {
            "gpu_avg_elapsed_ms": gpu_avg,
            "cpu_avg_elapsed_ms": cpu_avg,
            "speedup_cpu_vs_gpu": round(cpu_avg / gpu_avg, 2) if gpu_avg else 0.0,
            "gpu_saves_ms": round(cpu_avg - gpu_avg, 2),
        }

    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Ollama GPU and CPU backends with the same prompts.")
    parser.add_argument("--gpu-base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--cpu-base-url", default="http://127.0.0.1:11435")
    parser.add_argument("--chat-model", default="qwen2.5:3b")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    cases = build_cases()
    payload: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs_per_case": args.runs,
        "backends": {
            "gpu": {
                "base_url": args.gpu_base_url,
                "cases": {},
            },
            "cpu": {
                "base_url": args.cpu_base_url,
                "cases": {},
            },
        },
    }

    for backend_name, base_url in (("gpu", args.gpu_base_url), ("cpu", args.cpu_base_url)):
        for case_name, case in cases.items():
            if case["type"] == "generate":
                payload["backends"][backend_name]["cases"][case_name] = measure_generate(
                    base_url=base_url,
                    model=args.chat_model,
                    prompt=case["prompt"],
                    runs=args.runs,
                    timeout=args.timeout,
                )
            else:
                payload["backends"][backend_name]["cases"][case_name] = measure_embed(
                    base_url=base_url,
                    model=args.embed_model,
                    text=case["prompt"],
                    runs=args.runs,
                    timeout=args.timeout,
                )

    payload["comparison"] = compare_backend_metrics(payload)

    output_arg = str(args.output or "").strip()
    if output_arg:
        target = Path(output_arg)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

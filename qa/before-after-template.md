# Benchmark Before vs After

## Cara pakai cepat
1. Jalankan baseline (sebelum patch):
   - `python qa/benchmark_chat.py --tag before`
2. Jalankan setelah patch:
   - `python qa/benchmark_chat.py --tag after`
3. Isi tabel ringkasan di bawah dari file JSON output.

## Ringkasan metrik

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| TTFT p50 (ms) |  |  |  |
| TTFT p95 (ms) |  |  |  |
| Total p50 (ms) |  |  |  |
| Total p95 (ms) |  |  |  |
| Total avg (ms) |  |  |  |
| Error query count |  |  |  |
| Contact probe called |  |  |  |
| Contact-flow handled |  |  |  |

## Definition of Done

- TTFT p50 stream <= 5000 ms
- TTFT p95 stream <= 7500 ms
- Total latency p50 <= 10000 ms
- Error query count = 0 pada 10-query testset
- Contact-flow hanya dipanggil saat relevan (probe ratio turun vs baseline)
- Tidak ada HTTP 500 dari retrieval/Chroma selama benchmark

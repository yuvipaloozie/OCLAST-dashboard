# CPU laptop and packaged-app reliability

This pass targets local Windows use in Dr. Taval's lab. The model checkpoint,
V9 preprocessing, threshold, watershed settings and measurement definitions stay
unchanged. These results validate the Windows v1.3.1 release.

## Changes

- CPU inference uses half the logical cores, capped at four, and does not spin
  idle worker threads. CPU memory-pattern caching is disabled; BLAS/background
  pools default to one thread before import, and OpenCV uses one thread. `OCLAST_CPU_THREADS` permits a smaller budget.
- GPU execution failure releases the failed session before allocating CPU
  fallback. The failed tile is retried; health polling does not wait for a tile.
- Whole-image separation avoids an implicit int64 copy of the component map and
  promptly releases component buffers. Large dense regions are checked against
  available memory before distance transform and watershed allocations.
- Imports decode from disk in a worker thread, rather than retaining the entire
  uploaded TIFF in a second byte string on the request loop. Single 8-bit RGB
  images are limited to 64 megapixels and 512 MB. Stack inputs are rejected.
- Only one import, analysis, or ZIP build occupies the heavy-operation slot.
  Another request receives a retry message instead of extending an unbounded
  queue. Tiles and metadata remain accessible.
- ZIP exports are built on temporary disk storage and streamed, then removed.
  Prediction files are replaced atomically; failed imports remove partial files.
- The executable locks its project directory before loading projects, reserves
  the actual listening socket, handles port conflicts, and opens the browser
  after startup. Logs rotate under `%LOCALAPPDATA%/OCLAST/logs`.

## Tests and interpretation

The regression suite injects low available memory, disk-full failures, invalid
images, GPU initialization/run failures, concurrent native inference callers,
duplicate startup, and process termination. Failure tests also check that the
next operation can succeed. No test changes a user's saved projects.

The exact original and revised separation algorithms were compared using the
cached probability map for the 8,057 × 7,479 sample image. Both produced 858
objects and identical label bytes. Peak working set fell from 1,067.1 to 780.8 MiB
(about 27%); elapsed time was 3.16 versus 3.12 seconds. This measures separation
in a separate process, not peak memory of the entire running application.
Dense foreground and 466,489 isolated components were also tested.

CPU final-head tile testing completed 24 inferences across four real TIFF crops.
Median time was 4.88, 2.81 and 1.99 seconds with one, two and four threads.
The output arrays matched exactly across thread settings. These are Intel i7-10700 desktop CPU
measurements (8 cores/16 logical processors, about 32 GiB installed RAM),
potentially affected by concurrent tests/builds, not laptop promises.

An additional 24-run comparison across four real TIFF crops tested allocation
policies. Disabling CPU memory patterns and limiting background pools reduced
peak model-process commit from 3,077.8 to 1,536.2 MiB and peak working set from
1,992.8 to 1,095.4 MiB. Every output matched bit for bit. Second-pass tile medians
were 2.23 versus 2.38 seconds (about 7% slower in this small, contended test).
This balanced setting is adopted. Disabling the CPU arena saved more retained
memory but was slower, so that variant is deferred. These figures concern the
model tile process; they are not whole-app memory measurements.

The executable stress harness is `packaging/verify_cpu_package.py`. It runs from
an empty directory with Python/Conda variables removed and Windows-only PATH,
CPU-only execution and a 4 GiB per-process commit limit. CPU counts are
configurable; the initial stress run uses two logical CPUs, and the optimized
candidate is validated with four logical CPUs/threads. It
checks the full image, repeated crops, response latency, exports, duplicate
launch and reopening saved results. Its JSON records the tested executable hash.
Commit limits and affinity do not reproduce a particular laptop or constrain
the physical memory available to the OS. A real CPU-only lab laptop remains a
required deployment pilot, especially for Defender, drivers and thermal limits.

## Packaged candidate results (2026-11-02)

The final executable SHA256 is
`82ac9c9135e8a22a43e4b9664daa62aa17c1ae945ab749667fa3d2d937e6c3bf`.

| Check | Result |
| --- | --- |
| Full 8,057 × 7,479 image, CPU only, four logical CPUs, 4 GiB process ceiling | 858 objects, 794.94 seconds (13m 15s), completed |
| Largest process peak commit | 2,488,635,392 bytes (2.32 GiB) |
| Sampled peak process-tree working set | 1,902,190,592 bytes (1.77 GiB); sampling can miss short peaks |
| Health response latency during full inference | 16 ms at 95th percentile; 94 ms maximum |
| Full-image labels versus original cached-reference separation | Exact identical SHA256; 858 objects |
| Three repeated real 1,024 × 1,024 crops | Identical labels, probabilities and measurements; about 11–12 seconds each |
| Private-memory change, first to third repeated crop | +872,448 bytes; short repeatability check, not a long-term leak guarantee |
| Tile layers, CSV, analysis ZIP, duplicate launch, stop/reopen | Passed |
| Forced stop during inference, restart, rerun | Passed; saved source preserved |
| Actual allocation failure under 1 GiB commit ceiling | Clear error; health/list remained available; rerun with memory succeeded |
| Automatic GPU selection on final EXE | DirectML; 28 crop objects in 3.59 seconds, no fallback |
| Regression checks | 59 Python tests + 5 frontend tests; frontend lint/build passed |

The initial intermediate executable with the previous allocation defaults reached
all 240 tiles but failed at whole-image separation under the same 4 GiB ceiling.
The final policy completed separation and saving. CPU counts differed (two versus
four logical CPUs), and concurrent test activity affected timing; use this as
resource/failure evidence, not a before/after speed benchmark. The previous
background defaults also failed startup at a 1 GiB commit ceiling; the optimized
candidate started and returned a recoverable inference error at that limit.

Reports preserve both passes and failures in [validation](validation/).
The [manifest](validation/v1.3.1-manifest.json) records the exact executable,
source fingerprints, hardware and test scope. The v1.3.1 release includes this tested executable and its checksum.

## Quantization: a separate accuracy experiment

Do not silently replace the deployed model. A suitable next candidate is static
INT8 quantization with QDQ and representative V9-preprocessed calibration tiles;
ONNX Runtime recommends static quantization for CNNs. See the official
[quantization guide](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html).

Evaluate held-out whole images and edge/low-contrast/large-object crops. Compare
foreground overlap, instance matching, counts, per-object area and circularity
against FP32 and reviewed ground truth. Agree acceptable differences before
choosing a candidate. Benchmark on the actual target laptop: INT8 speedups depend
on supported operators and CPU instructions, and accuracy can change. Keep FP32
available and record the model hash and precision for every saved analysis.

Quantization targets model weights and activations; it does not remove the
full-resolution probability, component, label or watershed arrays. Those still
need memory admission checks. FP16 is not assumed to improve ordinary CPU use.

## Remaining limits

- These checks reduce risk; they cannot guarantee that native libraries never
  crash or that another application will not consume RAM after admission.
- Eight GB RAM is a pilot target, not yet a verified minimum. Very large or dense
  images can be rejected; crop them rather than forcing the allocation.
- Closing the console stops the app. Interrupted analysis can be rerun from the
  original saved source, but progress is not resumed from individual tiles.
- A one-file executable extracts bundled libraries to temporary storage on each
  launch. Slow first startup or antivirus scanning can still occur. Signing or
  a conventional installer can be evaluated after the lab pilot.

## v1.4.0 packaged batch validation

The v1.4.0 executable repeats the full-image CPU test under four logical CPUs/threads and a 4 GiB per-process commit ceiling. The full 8,057 � 7,479 image produced 858 objects in 696.97 seconds. Exports, repeated crops, duplicate startup, and restart preservation passed. A separate actual-EXE test runs a three-image queue under two logical CPUs: duplicate imports reuse saved projects, a paused queue survives restart, and all-object CSV retains every detection.

See [the v1.4.0 validation manifest](releases/v1.4.0-validation.json) for executable SHA256, memory, latency, scope, and recorded results. The model and segmentation definitions are unchanged.

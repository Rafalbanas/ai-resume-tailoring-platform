# Draft integrity and Ollama selection

Draft persistence validates a fresh serialized snapshot after all analysis and
resume mutations. Only the display reasoning summary is bounded to its model
limit; detailed issue lists remain intact. The writer flushes and fsyncs a
temporary file in the draft directory, atomically publishes it, and reads it
back through the normal loader before returning its ID. A failed readback
removes the unpublished result from the workflow. The task manager sets
`COMPLETED` only after this operation succeeds.

The shared loader also bounds oversized summaries in older drafts in memory.
It does not rewrite old files. Invalid stored data raises `DraftDataError`,
separately from a missing file. Analysis and generation pages return an HTML
recovery page with history/new-analysis links (422 for invalid data, 404 for
a missing draft), retaining the current account's root path.

The new-analysis form reads `/api/tags` from the configured Ollama server.
Model names retain their exact case and tags. An explicit selection and its
32,768/65,536/98,304/131,072 context are included in the task payload and idempotency key;
reopening a task restores those choices. Gemini ignores Ollama selections.
An empty model selection retains the default model but applies the selected
context. The new form defaults to 65,536 tokens; older task payloads without
context retain their previous behavior. Listing failures leave the form usable and display an availability
message.

Before inference, `/api/tags` rechecks availability and `/api/show` checks the
advertised model context limit. Each selected model gets an isolated provider
copy, metrics, and context-local run state, sharing the original inference
semaphore. A tokenizer verified only for the default model is not reused for
a different model. Existing conservative planning remains available.
The actual model/context are sent to `/api/chat`. Existing automatic fallback
settings still apply; a failed selected model can fall back when enabled.
Model downloads and Ollama connection setup are not performed by this UI.

Validation:

```sh
.venv/bin/python -m pytest tests/test_storage.py tests/test_ollama_model_selection.py tests/test_draft_errors.py tests/test_draft_pipeline.py tests/test_ollama_provider.py -q
```

48 tests passed. Tests use synthetic profiles and mocked Ollama responses;
they do not establish quality, speed, or GPU memory requirements of a real
27B model. Production's configured Ollama endpoint refused connections during
implementation, so live model selection and generation remain unverified.

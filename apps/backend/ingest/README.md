# Teacher Examples Ingest

This pipeline converts teacher reference materials into structured case data for downstream graph/KG usage.

## Step 1: Build metadata

```bash
uv run python -m ingest.build_metadata
```

Outputs: `data/corpus/teacher_examples/metadata.csv`

Highlights:
- Auto detect category (folder-based)
- Parse quality grading (`A/B/C`)
- Appendix evidence detection (`附录/附件/截图/...`)
- Preserve manual columns (`education_level/year/award_level/school`)

## Step 2: Extract structured cases

```bash
uv run python -m ingest.extract_case_struct
```

Outputs:
- `data/graph_seed/case_structured/case_*.json`
- `data/graph_seed/case_structured/manifest.json`
- `data/graph_seed/case_structured/summary.json`

## One-shot pipeline

```bash
uv run python -m ingest.pipeline
```

## Notes

- Documents with `parse_quality=C` are skipped by default.
- The extractor keeps original files unchanged and only generates derived metadata/JSON artifacts.

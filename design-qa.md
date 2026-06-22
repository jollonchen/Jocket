**Source visual truth**

- `/var/folders/lt/zgz1r69d1cl7lj_6dwlbkkjc0000gn/T/codex-clipboard-256f9fc5-c7cd-4240-95d0-9542f6f068cc.png`
- `/var/folders/lt/zgz1r69d1cl7lj_6dwlbkkjc0000gn/T/codex-clipboard-50455c94-7e25-4233-aa0f-de44a68243d5.png`
- `/var/folders/lt/zgz1r69d1cl7lj_6dwlbkkjc0000gn/T/codex-clipboard-98ef2bd9-16b4-4121-9232-b24af64a02df.png`

**Implementation**

- Local target: `http://127.0.0.1:8503` (fresh server); Safari also hot-reloaded the same source at `http://localhost:8501` for visual interaction.
- Implementation screenshot: `/tmp/jocket-layout-qa.png`.
- Viewport/state: desktop Safari, 3024 × 1964 screen capture; 个股行情 -> 生益科技 -> 财务质量摘要 / 可解释评分.

**Full-view comparison evidence**

- The first supplied screenshot and `/tmp/jocket-layout-qa.png` were opened together at original resolution.
- The source showed two KPI rows colliding with the following explanation block. The implementation gives every 2x1 KPI card a content-sized 176px grid track plus an independent row gap; both visible KPI rows remain separated and contained.
- Section headings, cards, and following content now keep an explicit vertical rhythm instead of relying on conflicting minimum heights.

**Focused region comparison evidence**

- Financial quality: eight KPI cards render as two clean four-card rows with readable label/value/body spacing and no collision.
- Explanation panel: accessibility inspection confirms five individual research-point cards and separate boundary-condition cards instead of a flat Markdown list.
- Score dimensions: accessibility state confirmed all six expanders initially report `off`. Clicking the first item changed it to `on`, exposed its detail/table content, and the next render returned to the requested collapsed default.
- Typography, colors, and copy retain the existing Jocket dark glass language; no new image assets were introduced.

**Findings**

- No actionable P0/P1/P2 issues remain in the requested desktop surfaces.
- The fixed bottom command bar can cover a small portion of content near the viewport bottom while scrolling; this is existing app behavior and not caused by this patch.

**Patches made**

- Removed the grid-track/min-height conflict that caused 2x1 KPI cards to overlap.
- Added more card padding, line height, row gap, and section separation on result pages.
- Replaced score and fundamental explanation text walls with structured research-point and limitation cards.
- Restyled score-dimension labels and tightened the gap between collapsed controls.
- Changed every score-dimension expander to `expanded=False`.
- Added desktop/mobile layout rules and regression tests.

**Follow-up polish**

- P3: a later pass could reduce the fixed command bar's visual footprint on very short desktop viewports.

final result: passed

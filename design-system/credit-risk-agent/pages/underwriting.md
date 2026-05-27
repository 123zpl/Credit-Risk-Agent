# Underwriting Page Override

> Overrides MASTER.md for the 贷前授信审批 page only.

## Layout

**Pattern:** Split Panel — 40% list / 60% detail
- Left: applicant list + toolbar (generate, filter, refresh)
- Right: applicant detail + action + result (or empty state)

## Status Badge Colors

| Status         | Color class                         | Label        |
|----------------|-------------------------------------|--------------|
| PENDING        | `bg-muted text-muted-foreground`    | 待审批       |
| RUNNING        | `bg-blue-100 text-blue-700` + pulse | 审批中       |
| APPROVED       | `bg-emerald-100 text-emerald-700`   | 已批准       |
| REJECTED       | `bg-red-100 text-red-700`           | 已拒绝       |
| MANUAL_REVIEW  | `bg-amber-100 text-amber-700`       | 人工复核     |
| FAILURE        | `bg-red-100 text-red-600`           | 任务失败     |

## Decision Card Colors

| Decision      | Header bg                        | Icon          |
|---------------|----------------------------------|---------------|
| APPROVED      | `bg-emerald-50 border-emerald-200` | CheckCircle  |
| REJECTED      | `bg-red-50 border-red-200`       | XCircle       |
| MANUAL_REVIEW | `bg-amber-50 border-amber-200`   | AlertCircle   |

## Risk Score Gauge

- Large centered number (font-size: 3rem, font-weight: 700)
- Color: ≥700 emerald, 500-699 amber, <500 red
- Subtitle: risk_grade letter (A/B/C…)
- Thin circular SVG arc below the number (decorative, stroke-width=8)

## Score Breakdown

- Horizontal mini-bars for each factor (fico, dti, delinq, emp_length, home, revol_util, inquiries)
- Negative scores shown in red, positive in emerald, zero in muted

## Approval Report

- Rendered with react-markdown
- Contained in a scrollable box (max-h-56) with `prose prose-sm` styling
- Collapsible (collapsed by default)

## Anti-Patterns (this page)

- ❌ Do NOT block the list while an individual approval is running
- ❌ Do NOT navigate away from the list after approving
- ❌ Do NOT auto-refresh the list during polling (only update the selected item's status)

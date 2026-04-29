# Renderer Tunability and Visual Documentation (Step 17)

This document identifies the hard-wired visual aspects of the GPMPE renderer and proposes a plan for externalizing them into tunable data objects (YAML/SQLite).

## 1. Currently Hard-Wired Visual Aspects

The following visual properties are currently "baked-in" to `backend/app/renderer.py` and cannot be easily changed without modifying Python code.

### 1.1 Layout Proportions
*   **Global Layout:** The relative heights of the Header (`112pt`), Featured Section (`230pt`), and Secondary Section (`302pt`) are fixed.
*   **Gaps:** The `14pt` section gap is hard-coded.
*   **Margins:** The `36pt` page margin is a global constant.

### 1.2 Component Typography
*   **Business Identity:**
    *   Name: `Helvetica-Bold, 22pt`.
    *   Subtitle: `Times-Italic, 16pt`.
*   **Featured Section:**
    *   Main Title: `Helvetica-Bold, 21pt`.
    *   Subtitle: `Times-Italic, 12pt`.
*   **Compact Card (Featured Items):**
    *   Title: `Helvetica-Bold, 10pt`.
    *   Price/Duration: `11pt` (dynamic adjustment logic).
*   **Secondary Section (List Items):**
    *   Name: `Helvetica-Bold, 11pt`.
    *   Duration: `Helvetica, 11pt`.
    *   Price: `Helvetica-Bold, 11pt`.
*   **Discount/Legal:**
    *   Various fonts from `Helvetica` and `Times` at sizes ranging from `8.5pt` to `17pt`.

### 1.3 Visual Styling
*   **Border Radii:** Panel (`24pt`), Card (`12pt`), Strip (`10pt`).
*   **Stroke Widths:** Range from `1pt` to `2pt`.
*   **Color Defaults:** Cream background (`#FBF7F4`), Ink text (`#181818`).
*   **Spacing Logic:** Internal padding for cards (e.g., `body_padding_bottom = 7pt`).

---

## 2. Externalization Proposal

To increase renderer flexibility without code changes, we should migrate these hard-wired values into the `layout_json` (template-level) or `style_json` (component/item-level) fields.

### 2.1 Template-Level Overrides (`layout_json`)
Move global proportions and typography into the `template_definitions` table.

**Proposed Additions to `layout_json`:**
```json
{
  "typography": {
    "business_name": {"font": "Helvetica-Bold", "size": 22},
    "business_subtitle": {"font": "Times-Italic", "size": 16},
    "section_title": {"font": "Helvetica-Bold", "size": 21},
    "section_subtitle": {"font": "Times-Italic", "size": 12}
  },
  "geometry": {
    "section_gap": 14.0,
    "page_margin": 36.0,
    "header_height": 112.0
  }
}
```

### 2.2 Component-Level Overrides (`style_json`)
Move specific component visuals into the `campaign_components` table.

**Proposed Additions to `style_json`:**
```json
{
  "border_radius": 12.0,
  "stroke_width": 1.5,
  "font_sizes": {
    "item_name": 11.0,
    "item_value": 11.0,
    "item_duration": 11.0
  },
  "padding": {
    "bottom": 7.0,
    "top": 17.0
  }
}
```

### 2.3 Implementation Strategy
1.  **Refactor `_palette` and `_layout`:** Update these helpers to prioritize data from `effective_values` and `style_json`.
2.  **Update `_draw_*` Primitives:** Pass style objects into drawing functions rather than using constants.
3.  **Chat Integration:** Add commands like `set component style border_radius to 10` (as identified in Step 16).

## 3. Visual Centering Logic Documentation

The renderer uses a "Visual Centering" algorithm for compact cards. This should be preserved as the default behavior even when sizes are tuned:

1.  **Baseline 1 (Price):** Fixed at `y + padding_bottom`.
2.  **Baseline 2 (Name):** Centered within the accent header bar.
3.  **Centering (Duration):** The Duration label is placed at `(Price Top + Name Baseline) / 2`, adjusted for the glyph's cap-height.

This logic ensures symmetry regardless of font size, provided the padding values are also exposed as tunable parameters.

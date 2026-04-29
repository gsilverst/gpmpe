# GPMPE Data and Command Gap Analysis (Step 16)

This report identifies the gaps between the underlying data schema (SQLite/YAML) and the mutation capabilities of the natural-language chatbot interface.

## 1. Schema Coverage Analysis

The following tables show which fields in the data model are currently "reachable" via chat commands.

### 1.1 Business Profile
| Field | DB Column | Chat Mutable? | Note |
| :--- | :--- | :---: | :--- |
| Legal Name | `legal_name` | Yes | |
| Display Name | `display_name` | Yes | |
| Timezone | `timezone` | Yes | |
| Active Status | `is_active` | Yes | |
| Primary Phone | `business_contacts` | Yes | Maps to phone contact. |
| Primary Email | `business_contacts` | **No** | Missing from `BUSINESS_FIELDS`. |
| Primary Website | `business_contacts` | **No** | Missing from `BUSINESS_FIELDS`. |
| Address Line 1 | `business_locations.line1` | Yes | |
| Address Line 2 | `business_locations.line2` | Yes | |
| City | `business_locations.city` | Yes | |
| State | `business_locations.state` | Yes | |
| Postal Code | `business_locations.postal_code` | Yes | |
| Country | `business_locations.country` | Yes | |
| Location Label | `business_locations.label` | **No** | Hard-wired to `None` in mutation. |
| Business Hours | `business_locations.hours_json` | **No** | No command pattern for JSON hours. |

### 1.2 Campaign
| Field | DB Column | Chat Mutable? | Note |
| :--- | :--- | :---: | :--- |
| Name (Slug) | `campaign_name` | **No** | Currently internal/derived. |
| Title (Headline) | `title` | Yes | |
| Objective | `objective` | Yes | |
| Footnote Text | `footnote_text` | Yes | |
| Status | `status` | Yes | |
| Start Date | `start_date` | Yes | |
| End_Date | `end_date` | Yes | |
| Additional Details | `details_json` | **No** | |

### 1.3 Campaign Components
| Field | DB Column | Chat Mutable? | Note |
| :--- | :--- | :---: | :--- |
| Component Key | `component_key` | Yes | Via `rename` or `component-key field`. |
| Component Kind | `component_kind` | Yes | |
| Display Title | `display_title` | Yes | |
| Background Color | `background_color` | Yes | |
| Header Accent | `header_accent_color` | Yes | |
| Subtitle | `subtitle` | Yes | |
| Description | `description_text` | Yes | |
| Footnote | `footnote_text` | Yes | |
| Render Region | `render_region` | **No** | Derived from `component_kind` defaults. |
| Render Mode | `render_mode` | **No** | Derived from `component_kind` defaults. |
| Style Settings | `style_json` | **No** | |
| Display Order | `display_order` | **No** | No explicit "move" or "set order" cmd. |

### 1.4 Component Items
| Field | DB Column | Chat Mutable? | Note |
| :--- | :--- | :---: | :--- |
| Item Name | `item_name` | Yes | |
| Item Kind | `item_kind` | Yes | |
| Duration Label | `duration_label` | Yes | |
| Item Value | `item_value` | Yes | |
| Background Color | `background_color` | Yes | |
| Description | `description_text` | Yes | |
| Terms | `terms_text` | Yes | |
| Render Role | `render_role` | **No** | |
| Style Settings | `style_json` | **No** | |
| Display Order | `display_order` | **No** | Handled by ordinal placement in `add`. |

---

## 2. Command Pattern Gaps

Beyond field mapping, certain structural operations are missing from the chatbot interface.

### 2.1 Missing Entity Operations
1.  **Campaign Deletion:** There is no `delete the campaign <name>` command.
2.  **Offer Management:** There is no command to `add a new offer` or `delete offer <id>`. (While components have replaced simple offers in rich mode, the `campaign_offers` table is still active for simple mode).
3.  **Offer Details:** `offer_name` and `offer_type` are missing from `OFFER_FIELDS` patterns.
4.  **Business Contact Expansion:** The chatbot only supports `phone`. It should support `email` and `website`.
5.  **Component Addition:** There is no explicit `add a new component called <name>` command (only `add item` and `cloning`). Users cannot currently create a brand new section from scratch via chat.

### 2.2 Orchestration Gaps
1.  **Multiple Locations:** The current `business` mutation logic deletes all locations and inserts one. It doesn't support managing multiple locations or specific location labels.
2.  **Bulk Edits:** `change <field> for all items` exists, but `change <field> for all components` is limited.

---

## 3. Proposed Enhancements

To achieve 100% campaign-building parity, the following patterns should be added to `chat.py`:

### 3.1 New Fields for Existing Patterns
*   Add `email` and `website` to `BUSINESS_FIELDS`.
*   Add `offer_name` and `offer_type` to `OFFER_FIELDS`.
*   Add `render_region` and `render_mode` to `COMPONENT_FIELDS`.

### 3.2 New Command Patterns
1.  **Campaign Management:**
    *   `delete campaign <name>`
2.  **Offer Management:**
    *   `add a new offer called <name>`
    *   `delete offer <id>`
3.  **Component Management:**
    *   `add a new component called <name> [of type <kind>]`
4.  **Location Management:**
    *   `set email to <value>`
    *   `set website to <value>`
5.  **Style/JSON Management:**
    *   Initial support for simple style overrides: `set component <name> style <key> to <value>`.

## 4. Conclusion

The current chatbot is highly effective for *tuning* existing campaigns and *adding content* (items), but it lacks the primitives for *structural creation* (adding components/offers) and *administrative cleanup* (deleting campaigns). Addressing the "Missing Fields" and "Entity Operations" will complete the 100% parity goal.

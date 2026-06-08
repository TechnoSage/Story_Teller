# TechnoSage Application Patterns

Single source of truth for UI structure, naming, icons, and patterns used across
**all** TechnoSage applications. Every new app created from the scaffold inherits
these conventions. Deviating from these patterns requires deliberate justification.

---

## Quick-start from scaffold

```bash
# 1. Copy scaffold into new project
cp -r scaffold/ my_new_app/

# 2. Rename placeholders
#    APP_NAME      → Your App Name
#    APP_SUBTITLE  → Short description
#    APP_VERSION   → 1.0.0

# 3. Install requirements
cd my_new_app && pip install -r requirements.txt

# 4. Run
python run.py
```

---

## Page structure

Every page uses the same 3-zone layout from `base.html`:

```
┌─────────────────────────────────────────────────────────┐
│  TOPBAR  [toggle] [title] [badges] [OS] [⚙] [🌙] [?]  │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ SIDEBAR  │               CONTENT                       │
│  (nav)   │    section-pane (shown/hidden by JS)        │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

- Sidebar: `id="sidebar"`, collapsible, state saved in `localStorage`
- Content: `id="page-content"` > `div.p-3.p-lg-4` > `div.section-pane`
- Section switching: `showSection('sectionId')` JS function

---

## Navigation conventions

### Sidebar section labels
```html
<div class="nav-section-label">Section Title</div>
```

### Sidebar nav links
```html
<a class="nav-link" href="#" id="nav-mypage"
   data-tooltip="My Page — short description"
   onclick="showSection('mypage');return false;">
  <i class="bi bi-ICON"></i><span class="nav-label">My Page</span>
</a>
```

### Active state
Managed automatically by `showSection()`. Do NOT set `active` class manually.

---

## Icons — standard set

| Use              | Icon class               | Colour token      |
|------------------|--------------------------|-------------------|
| Dashboard        | `bi-speedometer2`        | `text-primary`    |
| Settings         | `bi-sliders`             | `text-secondary`  |
| Git / VCS        | `bi-git`                 | `text-warning`    |
| Notifications    | `bi-bell`                | default           |
| Help / Docs      | `bi-question-circle`     | `text-info`       |
| Changelog        | `bi-clock-history`       | default           |
| Support          | `bi-headset`             | `text-warning`    |
| Dark mode        | `bi-moon-fill` / `bi-sun-fill` | default     |
| Build / Compile  | `bi-rocket-takeoff`      | `text-success`    |
| Error / Alert    | `bi-exclamation-triangle`| `text-warning`    |
| Fatal / Blocked  | `bi-x-circle-fill`       | `text-danger`     |
| OK / Pass        | `bi-check-circle-fill`   | `text-success`    |
| Info popup (ℹ)  | inline `ℹ` text          | `var(--bs-info)`  |
| Publisher        | `bi-building`            | `text-secondary`  |
| AI / Agent       | `bi-cpu`                 | `text-secondary`  |
| OS — Windows     | `bi-windows`             | `#0078d4` (blue)  |
| OS — Linux       | `bi-ubuntu`              | `#39ff14` (green) |
| OS — macOS       | `bi-apple`               | `#a2aaad` (grey)  |

---

## Button styles

| Purpose          | Class                          | Notes                         |
|------------------|--------------------------------|-------------------------------|
| Primary action   | `btn btn-primary`              | Save, Submit, Run             |
| Secondary        | `btn btn-outline-secondary`    | Cancel, Back, Browse          |
| Danger           | `btn btn-outline-danger`       | Delete, Clear, Remove         |
| Info action      | `btn btn-outline-info`         | Update, Refresh               |
| Success          | `btn btn-success`              | Confirm, Apply                |
| Topbar button    | `topbar-btn`                   | Icon-only; use `topbar-btn-toggle/danger/info` variants |
| Inline ℹ button  | `btn btn-link p-0 ms-1`        | Next to each option; opens info popup |

---

## Card conventions

### Standard card
```html
<div class="card">
  <div class="card-header bg-transparent border-0 pb-0">
    <h6 class="fw-bold mb-0"><i class="bi bi-ICON me-1 text-secondary"></i>Title</h6>
  </div>
  <div class="card-body">
    <!-- content -->
  </div>
</div>
```

### Metric card
```html
<div class="metric-card">
  <div class="metric-value">42</div>
  <div class="metric-label">Label</div>
  <div class="metric-sub text-muted">Sub-text</div>
</div>
```

Card CSS (from `default-styles.css` — never override with `border-0` or `shadow-sm`):
- Background: `#1c1f24` (slightly darker than page `#212529`)
- Border: `1px solid rgba(255,255,255,.065)`
- Border-radius: `1.1rem`
- Box-shadow: 3D raised with inset highlight

---

## OS detection

Every app exposes `/api/platform` which returns:
```json
{ "ok": true, "os": "win", "os_display": "Windows", "os_full": "Windows 11" }
```

`os` values: `"win"` | `"linux"` | `"mac"`

`base.html` calls `_initOSDetect()` on `DOMContentLoaded`:
- Sets `_currentOS` global
- Updates the topbar OS badge
- Calls `_validateAllPaths()` to highlight mismatched path fields

To make a path field OS-aware, add its `id` to `_OS_PATH_FIELD_IDS` in a
`{% block scripts %}` override:
```html
{% block scripts %}{{ super() }}
<script>
_OS_PATH_FIELD_IDS = ['outputDir', 'dataRoot', 'iconFile'];
</script>
{% endblock %}
```

---

## Settings page conventions

Use `settings.html` as the starting point. All apps share:
- Publisher Name (`APP_PUBLISHER`)
- Support Email + URL (`SUPPORT_EMAIL`, `APP_SUPPORT_URL`)
- Claude API Key (`CLAUDE_API_KEY`) for AI-powered agents
- VCS Type selection (Git / SVN / Mercurial / Perforce / File Backup)

Global settings are saved via `POST /api/app-settings` and pushed to all project
profiles if the app uses multi-profile settings.

---

## Info popup (ℹ) pattern

Every user-selectable option that needs explanation gets an inline ℹ button:
```html
Option Label
<button type="button" class="btn btn-link p-0 ms-1 align-baseline"
        style="font-size:.72rem;color:var(--bs-info);"
        onclick="openInfoPopup('optionId')" title="Learn about Option">ℹ</button>
```

The popup content must also appear in the documentation page (`/help` or `/docs`)
at a matching anchor. Same content, two places — popup for quick reference,
docs for the full explanation.

---

## Agent endpoint pattern

Used for AI-powered "Update from Internet" buttons (VCS info, Code Protection, etc.):

```python
@app.route("/api/<feature>/update", methods=["POST"])
def api_feature_update():
    """Three-tier agent — works for every user on every system:
       1. Claude API  (if CLAUDE_API_KEY in settings) — best quality
       2. DuckDuckGo  (free, no key, always available)
       3. Built-in defaults — always succeeds, no internet needed
    """
    ...
```

The three tiers guarantee the feature never breaks for users without API keys.
See `builder_app.py` VCS and Code Protection agents for the reference implementation.

---

## Documentation structure

Every app has `/help` or `/docs` served from `templates/docs.html`.
Use the IntersectionObserver TOC scroll tracking — it's pre-built in `docs.html`.

Documentation section anchor convention:
- `#overview` — app description
- `#navigation` — sidebar nav guide
- `#settings` — settings page
- `#vcs` — version control section (if applicable)
- `#code-protection` — code protection section (if applicable)

---

## Heartbeat watchdog

The server exits when all browser tabs close (for single-user desktop apps).
The watchdog is pre-built in `app.py` with the Chrome double-sendBeacon fix.
**Do not change `_CLOSE_GRACE = 6.0`** — it prevents the server dying during
same-tab navigation when Chrome fires `sendBeacon` twice.

---

## Common API endpoints (all apps)

| Endpoint                    | Method | Purpose                          |
|-----------------------------|--------|----------------------------------|
| `/api/platform`             | GET    | OS detection                     |
| `/api/heartbeat?tab=<id>`   | POST   | Tab keep-alive                   |
| `/api/tab-close?tab=<id>`   | POST   | Tab unload signal                |
| `/api/app-settings`         | GET    | Load settings                    |
| `/api/app-settings`         | POST   | Save settings                    |

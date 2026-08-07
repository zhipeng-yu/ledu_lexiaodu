# Global Application Font Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase every 乐小读 window by one font level at startup and support process-local global `Ctrl + +` / `Ctrl + -` adjustment.

**Architecture:** Install one `ApplicationFontScaler` event filter on `QApplication`. It changes the inherited application point size and publishes the current delta through an application property; the chat window and toolbar recompute their few explicit font roles when Qt sends `ApplicationFontChange`.

**Tech Stack:** Python 3.11, PySide6 6.x, pytest 8.x, Qt offscreen UI tests

## Global Constraints

- Start at the system point size plus exactly 1pt.
- Change by exactly 1pt for each `Ctrl + +` or `Ctrl + -` key press while 乐小读 is active.
- Clamp the application base font to 8pt through 24pt.
- Keep adjustments in memory only; restarting restores system default plus 1pt.
- Preserve existing title/body/supporting-text hierarchy.
- Do not add settings UI, font buttons, persistence, `Ctrl + 0`, dependencies, or unrelated refactors.
- Use the project-local `.venv` for every Python command.

---

## File Structure

- Create `src/lexiaodu/font_scaling.py` for font state, event filtering, and explicit-style scaling.
- Create `tests/test_font_scaling.py` for focused real-Qt behavior tests.
- Modify `src/lexiaodu/app.py` and `tests/test_app.py` to install the scaler before constructing widgets.
- Modify `tests/test_selection.py` to keep its quit-policy test independent of font initialization.
- Modify `src/lexiaodu/chat.py`, `src/lexiaodu/toolbar.py`, `tests/test_chat.py`, and `tests/test_toolbar.py` so explicit roles track the global delta.
- Modify `README.md` and `docs/MANUAL_TEST_CHECKLIST.md` to document and manually verify the feature.

### Task 1: Application Font Scaler

**Files:**
- Create: `src/lexiaodu/font_scaling.py`
- Create: `tests/test_font_scaling.py`

**Interfaces:**
- Produces: `ApplicationFontScaler(application: QApplication, *, minimum_point_size: float = 8.0, maximum_point_size: float = 24.0, initial_increment: float = 1.0)`.
- Produces: `ApplicationFontScaler.current_point_size: float`.
- Produces: `scaled_point_size(base_point_size: float) -> float`.
- Stores the float delta in `QApplication` property `_lexiaodu_font_delta_points`.

- [ ] **Step 1: Write the default and shortcut tests**

Use a fixture that saves `QApplication.font()`, tracks created scalers, removes their event filters, clears `_lexiaodu_font_delta_points`, restores the font, closes widgets, and processes events after each test.

```python
def test_scaler_starts_one_point_larger_and_applies_to_new_widgets(qt_application):
    set_application_point_size(qt_application, 10.0)
    scaler = ApplicationFontScaler(qt_application)
    widget = QWidget()
    assert scaler.current_point_size == pytest.approx(11.0)
    assert qt_application.font().pointSizeF() == pytest.approx(11.0)
    assert widget.font().pointSizeF() == pytest.approx(11.0)


def test_ctrl_plus_and_minus_adjust_while_input_has_focus(qt_application):
    set_application_point_size(qt_application, 10.0)
    scaler = ApplicationFontScaler(qt_application)
    editor = QLineEdit()
    editor.show()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
    assert scaler.current_point_size == pytest.approx(12.0)
    QTest.keyClick(editor, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    assert scaler.current_point_size == pytest.approx(11.0)
    assert editor.text() == ""
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_font_scaling.py -q`

Expected: collection fails because `lexiaodu.font_scaling` does not exist.

- [ ] **Step 3: Implement the minimal controller**

```python
_FONT_DELTA_PROPERTY = "_lexiaodu_font_delta_points"
_FALLBACK_POINT_SIZE = 9.0


def scaled_point_size(base_point_size: float) -> float:
    application = QApplication.instance()
    raw_delta = (
        application.property(_FONT_DELTA_PROPERTY)
        if application is not None
        else None
    )
    try:
        delta = float(raw_delta)
    except (TypeError, ValueError):
        delta = 0.0
    return base_point_size + delta


class ApplicationFontScaler(QObject):
    def __init__(self, application, *, minimum_point_size=8.0,
                 maximum_point_size=24.0, initial_increment=1.0):
        super().__init__(application)
        self._application = application
        self._base_font = QFont(application.font())
        raw_size = self._base_font.pointSizeF()
        self._base_point_size = raw_size if raw_size > 0 else 9.0
        self._minimum_point_size = minimum_point_size
        self._maximum_point_size = maximum_point_size
        self._current_point_size = self._base_point_size
        application.installEventFilter(self)
        self._set_point_size(self._base_point_size + initial_increment)

    @property
    def current_point_size(self) -> float:
        return self._current_point_size

    def _set_point_size(self, requested: float) -> None:
        size = min(self._maximum_point_size,
                   max(self._minimum_point_size, requested))
        self._current_point_size = size
        self._application.setProperty(
            _FONT_DELTA_PROPERTY, size - self._base_point_size
        )
        font = QFont(self._base_font)
        font.setPointSizeF(size)
        self._application.setFont(font)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() is QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            modifiers = event.modifiers()
            controlled = modifiers & Qt.KeyboardModifier.ControlModifier
            excluded = modifiers & (
                Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
            if controlled and not excluded and event.key() == Qt.Key.Key_Plus:
                self._set_point_size(self._current_point_size + 1.0)
                return True
            if controlled and not excluded and event.key() == Qt.Key.Key_Minus:
                self._set_point_size(self._current_point_size - 1.0)
                return True
        return super().eventFilter(watched, event)
```

- [ ] **Step 4: Add boundary and compatibility tests**

Add real key-event tests that: press plus twice from a 23pt base and remain at 24pt; press minus repeatedly and remain at 8pt; send keypad Ctrl-plus and reach 12pt from a controlled 10pt base; install against a pixel-only font and reach the 9pt fallback plus 1pt. Each expected value is a literal, independent of implementation helpers.

```python
modifiers = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.KeypadModifier
)
QTest.keyClick(target, Qt.Key.Key_Plus, modifiers)
assert scaler.current_point_size == pytest.approx(12.0)
```

- [ ] **Step 5: Run GREEN and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_font_scaling.py -q`

Expected: all focused tests pass without warnings.

```powershell
git add -- src/lexiaodu/font_scaling.py tests/test_font_scaling.py
git commit -m "feat: add application font scaler"
```

### Task 2: Application Startup Integration

**Files:**
- Modify: `src/lexiaodu/app.py:146-149,368-371`
- Modify: `tests/test_app.py`
- Modify: `tests/test_selection.py:36-68`

**Interfaces:**
- Consumes `ApplicationFontScaler` from Task 1.
- Changes `_configure_application(application: QApplication, app_name: str)` to return the installed scaler.

- [ ] **Step 1: Write a failing configuration test**

Set `QT_QPA_PLATFORM=offscreen` before PySide6 imports in `tests/test_app.py`.

```python
def test_configure_application_installs_default_font_increase():
    application = QApplication.instance() or QApplication([])
    original_font = QFont(application.font())
    base_font = QFont(original_font)
    base_font.setPointSizeF(10.0)
    application.setFont(base_font)
    scaler = _configure_application(application, "乐小读")
    try:
        assert application.applicationName() == "乐小读"
        assert not application.quitOnLastWindowClosed()
        assert scaler.current_point_size == pytest.approx(11.0)
    finally:
        application.removeEventFilter(scaler)
        application.setProperty("_lexiaodu_font_delta_points", None)
        application.setFont(original_font)
        scaler.deleteLater()
        application.processEvents()
```

- [ ] **Step 2: Run the integration test and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_app.py::test_configure_application_installs_default_font_increase -q`

Expected: FAIL because `_configure_application` returns `None`.

- [ ] **Step 3: Install the scaler before any widget is built**

```python
def _configure_application(
    application: QApplication,
    app_name: str,
) -> ApplicationFontScaler:
    application.setApplicationName(app_name)
    application.setQuitOnLastWindowClosed(False)
    return ApplicationFontScaler(application)
```

Assign the return value to `font_scaler` in `run` and retain it through `application.exec()`. In `tests/test_selection.py`, directly set `application.setQuitOnLastWindowClosed(False)` because that test covers delayed selection lifetime, not application initialization, and remove its unused `_configure_application` import.

- [ ] **Step 4: Run nearby tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_app.py tests/test_selection.py -q`

Expected: all tests pass.

```powershell
git add -- src/lexiaodu/app.py tests/test_app.py tests/test_selection.py
git commit -m "feat: enable larger application font at startup"
```

### Task 3: Explicit Chat and Toolbar Font Roles

**Files:**
- Modify: `src/lexiaodu/chat.py:5-6,347-527`
- Modify: `src/lexiaodu/toolbar.py:3-6,8-76`
- Modify: `tests/test_chat.py`
- Modify: `tests/test_toolbar.py`

**Interfaces:**
- Consumes `scaled_point_size(base_point_size: float) -> float`.
- Uses role baselines: chat title 14pt, body/concern 11pt, section/risk 9pt, toolbar title 11pt.

- [ ] **Step 1: Write failing role-scaling tests**

For chat, set the application to 10pt, install the scaler, append a response, and locate `chatTitle`, `turnBody`, and `chatInput`. Assert 15pt/12pt, send Ctrl-plus to the input, process events, and assert 16pt/13pt.

For the toolbar, use the same controlled base and assert `QLabel#title` changes from 12pt to 13pt. Both tests restore the application font/property and remove the event filter in `finally`.

```python
assert title.font().pointSizeF() == pytest.approx(15.0)
assert body.font().pointSizeF() == pytest.approx(12.0)
QTest.keyClick(chat_input, Qt.Key.Key_Plus,
               Qt.KeyboardModifier.ControlModifier)
application.processEvents()
assert title.font().pointSizeF() == pytest.approx(16.0)
assert body.font().pointSizeF() == pytest.approx(13.0)
```

- [ ] **Step 2: Run the role tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat.py::test_chat_explicit_font_roles_follow_global_scaling tests/test_toolbar.py::test_toolbar_title_follows_global_scaling -q`

Expected: FAIL because current explicit styles remain fixed in pixels.

- [ ] **Step 3: Recompute only the existing font declarations**

Move each widget stylesheet into `_apply_style_sheet()`. Replace only current `font-size` literals with `scaled_point_size(...)` point values; keep all unrelated QSS byte-for-byte equivalent. Override `changeEvent`, call `super()` first, and refresh only for `QEvent.Type.ApplicationFontChange`.

```python
def changeEvent(self, event: QEvent) -> None:
    super().changeEvent(event)
    if event.type() is QEvent.Type.ApplicationFontChange:
        self._apply_style_sheet()
```

Do not add handlers to OCR or selection windows; they contain no explicit font sizes and inherit the application font automatically.

- [ ] **Step 4: Run affected UI tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_font_scaling.py tests/test_chat.py tests/test_toolbar.py tests/test_editor.py tests/test_selection.py tests/test_workflow.py -q`

Expected: all affected tests pass without Qt warnings or singleton state leakage.

```powershell
git add -- src/lexiaodu/chat.py src/lexiaodu/toolbar.py tests/test_chat.py tests/test_toolbar.py
git commit -m "feat: scale explicit window font roles"
```

### Task 4: Documentation and Final Verification

**Files:**
- Modify: `README.md:82-92`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md:34-48`

**Interfaces:**
- Documents Tasks 1-3; creates no runtime interface.

- [ ] **Step 1: Document the behavior**

Add README item 7:

```markdown
7. 所有窗口启动时默认使用“系统字号 + 1pt”；应用处于活动状态时可用 `Ctrl + +` / `Ctrl + -` 全局调节字号。调节仅在本次运行内有效，重启后恢复默认。
```

Add checklist row `F-11`:

```markdown
| F-11 | 分别在 OCR 校正和 AI 建议窗口按 `Ctrl + +` / `Ctrl + -`，再重启应用 | 所有已打开及随后打开的窗口同步逐级变化，文字和按钮无截断；重启后恢复“系统字号 + 1pt” |  |
```

- [ ] **Step 2: Run full verification**

Run: `git diff --check`

Run: `.\.venv\python.exe -B -m pytest -q`

Run: `$env:QT_QPA_PLATFORM='offscreen'; .\.venv\python.exe -B -m pytest tests/test_day5_acceptance.py -q`

Expected: no whitespace errors and all automated tests pass. Real Windows DPI, clipping at the 8pt/24pt bounds, and physical keyboard layout remain manual `F-11` checks and must not be reported as passed.

- [ ] **Step 3: Commit documentation**

```powershell
git add -- README.md docs/MANUAL_TEST_CHECKLIST.md
git commit -m "docs: explain global font shortcuts"
```

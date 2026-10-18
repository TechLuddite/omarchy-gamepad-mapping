import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Io
import QtTest
import qs.Commons
import qs.Commons as Commons

ShellRoot {
  Service {
    id: fake
    running: true
    switchedOn: true
    deviceAliases: ({"A": "B", "B": "Y"})
    bindings: [{combo: "B", label: "B", keys: "RETURN", repeat: true, hold: false, enabled: true}]
    labelOverrides: ({"A": "B"})
    connected: true
    deviceName: "Fixture controller"
    property int reloads: 0
    property int cancels: 0
    // Override startup and reload only: never create an input-reading daemon.
    function start() {}
    function reload() { reloads++ }
    onCapturingChanged: if (!capturing) cancels++
  }
  QtObject {
    id: fakeBar
    property QtObject shell: QtObject {
      function serviceFor(id) { return fake }
    }
    property string position: "top"
    property bool popoutSwitching: false
    property bool vertical: false
    property int barSize: 32
    property color barForeground: "#cacccc"
    property color urgent: "#ff0000"
    property string fontFamily: "monospace"
    property bool foregroundAnimationEnabled: false
    property var activePopout: false
    function requestPopout(owner) { activePopout = owner }
    function releasePopout(owner) { if (activePopout === owner) activePopout = false }
    function hideTooltip(item) {}
  }
  Loader {
    id: widgetLoader
    active: false
    sourceComponent: Component { BarWidget { bar: fakeBar } }
  }
  Loader {
    id: otherWidget
    active: false
    sourceComponent: Component { BarWidget { bar: fakeBar } }
  }
  Process {
    id: ipcClose
    property string method: "closeWindow"
    command: ["quickshell", "ipc", "-p", Quickshell.env("CONTROLLER_EDITOR_FIXTURE_PATH"), "--any-display", "call", "controller", ipcClose.method]
    property string reply: ""
    stdout: StdioCollector { onStreamFinished: ipcClose.reply = text }
    stderr: StdioCollector { onStreamFinished: ipcClose.reply += text }
    property int code: -1
    onExited: function(exitCode) { code = exitCode }
  }
  Process {
    id: compositorClose
    command: [Quickshell.env("CONTROLLER_TEST_SWAYMSG"), "-s", Quickshell.env("CONTROLLER_TEST_SWAYSOCK"), "[title=\"Controller Control\"] kill"]
    property int code: -1
    onExited: function(exitCode) { code = exitCode }
  }
  TestCase { id: keys; when: false }
  Timer {
    interval: 120
    running: true
    repeat: true
    property int stage: 0
    readonly property var widget: widgetLoader.item
    property var panel: null
    property var editor: null
    property var action: null
    property var description: null
    property real savedScroll: 0
    function check(ok, message) { if (!ok) throw new Error(message) }
    function find(item, predicate) {
      if (predicate(item)) return item
      var children = item.children || []
      for (var i = 0; i < children.length; i++) {
        var match = find(children[i], predicate)
        if (match) return match
      }
      return null
    }
    onTriggered: {
      if (stage === 1 && !editor.shortcutOptions.length && !editor.shortcutMessage) return
      if (stage > 0 && editor && editor.refreshing) return
      try {
        if (stage === 0) {
          check(fake.editor === null, "Checking bar state does not load editor")
          check(widget === null, "Launcher starts without any bar widget")
          panel = fake.ensureEditor()
          check(panel !== null && !panel.opened && !panel.windowOpened, "Editor starts closed")
          check(fake.ensureEditor() === panel, "IPC reuses one service editor")
          // The editor is reparented into the hidden popup initially.
          editor = panel.form
          check(editor !== null, "Shared content exists")
          action = find(editor, function(item) { return item.placeholderText !== undefined && item.placeholderText.indexOf("2. ") === 0 })
          description = find(editor, function(item) { return item.placeholderText === "Description (optional)" })
          check(action && description, "Manual key/command and description inputs retained")
          Commons.Color.shellValues = {"popups.text": "#64efab"}
          panel.openWindow()
          check(editor.shortcutOptions.length === 0, "Opening the editor does not fetch shortcuts")
          editor.loadShortcuts()
          editor.loadKeyboard()
          editor.loadMappings()
        } else if (stage === 1) {
          if (!editor.keyboardOptions.length) {
            if (!editor.keyboardMessage) return
            check(editor.keyboardMessage.indexOf("unavailable") >= 0, "Failed standard catalog keeps manual input available")
            editor.loadKeyboard()
            return
          }
          check(panel.windowOpened && !panel.opened, "Window opens independently of bar")
          widgetLoader.active = true
          check(widget.panel === panel && !widget.opened, "A later bar adopts the same service editor")
          fake.switchedOn = false
          check(editor.enabled && !editor.switchedOn, "Master switch off keeps editor controls usable")
          fake.switchedOn = true
          check(fake.cancels === 0, "Opening an inactive form does not resume external pause")
          check(editor.foreground.toString() === Commons.Color.popups.text.toString(), "Window uses popup foreground")
          check(editor.width >= 280 && editor.implicitHeight > 100, "Real form is laid out")
          check(editor.bindings.length === 1, "Daemon binding snapshot is used")
          check(editor.shortcutOptions.length >= 2, "Fake live shortcuts loaded")
          editor.draftIsCommand = true
          var shortcutPicker = find(editor, function(item) { return item.label === "CURRENT SHORTCUTS (OPTIONAL)" })
          check(shortcutPicker !== null, "Shared searchable picker exists")
          shortcutPicker.changed("SUPER+RETURN")
          check(!editor.draftIsCommand && action.text === "SUPER+RETURN" && description.text === "Terminal", "Picker fills editable keys and empty description")
          editor.chooseShortcut("PRINT")
          check(editor.draftDescription === "Screenshot", "A second choice replaces its unchanged automatic description")
          editor.chooseShortcut("SUPER+RETURN")
          check(editor.draftDescription === "Terminal" && editor.draftCombo.length === 0, "Selection changes the draft without saving")
          editor.draftDescription = "My description"
          editor.chooseShortcut("SUPER+RETURN")
          check(description.text === "My description", "Picker preserves a custom description")
          check(editor.keyboardOptions.length === 119, "Fake standard keys loaded")
          var keyboardPicker = find(editor, function(item) { return item.label === "STANDARD KEY (OPTIONAL)" })
          check(keyboardPicker !== null, "Shared searchable key picker exists")
          editor.draftIsCommand = true
          check(!keyboardPicker.visible, "Standard key picker is hidden in Command mode")
          editor.draftIsCommand = false
          keyboardPicker.changed("ENTER")
          check(action.text === "ENTER" && description.text === "My description", "Standard key fills editable input and preserves custom description")
          editor.draftDescription = ""
          editor.chooseKeyboardKey("LEFTSHIFT")
          editor.chooseKeyboardKey("RIGHTSHIFT")
          check(editor.draftDescription === "Right Shift", "Automatic key descriptions follow repeated selection")
          editor.draftAction = "SUPER+"
          editor.chooseKeyboardKey("A")
          check(editor.draftAction === "SUPER+A" && editor.draftCombo.length === 0, "Key choice appends to typed modifiers without saving")
          editor.editBinding({combo:"A",keys:"SUPER+RETURN",description:"Terminal"})
          editor.chooseKeyboardKey("F5")
          check(editor.draftDescription === "F5", "Loaded action description follows replacement key")
          editor.clearDraft()
          editor.refresh()
          editor.draftCombo = ["B"]
          editor.draftAction = "SUPER+"
          action.forceActiveFocus()
          keys.keyClick(Qt.Key_J)
          check(action.text === "SUPER+j", "Typing reaches manual input")
          keys.keyClick(Qt.Key_Tab)
          check(description.activeFocus, "Tab reaches description")
          editor.draftDescription = "custom keys"
          editor.saveDraft()
          editor.Window.window.height = 360
          var picker = find(editor, function(item) { return item.label === "CURRENT SHORTCUTS (OPTIONAL)" })
          picker.open()
        } else if (stage === 2) {
          var picker = find(editor, function(item) { return item.label === "CURRENT SHORTCUTS (OPTIONAL)" })
          check(picker.popupOpen && picker.filtered.length >= 2, "Real dropdown opens with captured compositor catalog")
          var list = find(editor.Window.window.contentItem, function(item) { return item.currentIndex !== undefined && item.count !== undefined && item.clip === true })
          check(list !== null && list.height > 0, "Dropdown has a clipped result viewport")
          var point = list.mapToItem(editor.Window.window.contentItem,0,0)
          check(point.y >= -1 && point.y + list.height <= editor.Window.window.height + 1, "Dropdown results fit inside a short window: " + point.y + " / " + list.height)
          picker.close()
          check(fake.reloads === 0 && editor.draftCombo.length === 0, "Saving clears draft without duplicate reload")
          check(editor.mappingState === "available", "Read-only discovery recovers after unavailable")
          fake._handle(JSON.stringify({event:"bindings", aliases:{A:"B",B:"Y"}, bindings:fake.bindings, labels:{A:"B"}}))
          check(editor.deviceAliases.A === "B", "Alias context follows the real service event handler")
          check(editor.matchingMappings.length === 1 && editor.matchingMappings[0].token === "A", "Raw A maps once to saved B; raw B maps elsewhere and is excluded")
          check(editor.matchingMappings[0].recorded === "B" && editor.matchingMappings[0].modifiers === 64 && editor.matchingMappings[0].submap === "desktop", "Alias and compositor context retained")
          var warning = find(editor, function(item) { return typeof item.text === "string" && item.text.indexOf("Potential overlap · B → B") === 0 })
          check(warning !== null && warning.text.indexOf("Super held · submap desktop") >= 0, "Visible advisory shows readable modifiers and submap")
          check(warning.text.indexOf("modifiers 64") < 0 && warning.text.indexOf("evdev") < 0, "Primary advisory omits implementation codes")
          check(editor.modifierContext(0) === "No modifiers", "No-modifier mapping is readable")
          check(editor.modifierContext(79) === "Shift held, Caps lock active, Ctrl held, Alt held, Super held", "Combined modifier context is readable")
          check(editor.modifierContext(176) === "Mod2 held, Mod3 held, Mod5 held", "Other Hyprland modifiers retain names")
          check(editor.modifierContext(320) === "Super held, Unknown modifiers 0x100", "Unknown bits are explicit")
          editor.draftCombo = ["Y"]
          check(editor.matchingMappings.length === 2, "Draft tokens add matching context without action-key inventory")
          editor.draftAction = "CUSTOM+KEYS"
          editor.draftDescription = "Keep custom input"
          editor.acceptMappingReport('{"available":true,"bindings":[]}')
          check(editor.mappingMessage.indexOf("No recognized") === 0, "Successful empty discovery differs from unavailable")
          editor.acceptMappingReport('{"available":false,"bindings":[]}')
          check(editor.mappingState === "unavailable" && editor.compositorBindings.length === 0, "Later unavailable response clears previous mappings")
          check(action.text === "CUSTOM+KEYS" && description.text === "Keep custom input", "Context updates preserve editable custom input")
          editor.refresh()
          editor.draftCombo = ["X"]
          editor.draftIsCommand = true
          editor.draftAction = "printf 'custom command'"
          editor.draftDescription = "custom command"
          editor.saveDraft()
        } else if (stage === 3) {
          check(fake.reloads === 0, "Manual command saved without duplicate reload")
          check(editor.mappingState === "available", "Discovery recovers without disturbing manual save")
          editor.beginCapture()
          check(fake.capturing, "Capture started through stub")
          action.forceActiveFocus()
          keys.keyClick(Qt.Key_Escape)
          check(panel.windowOpened && fake.capturing, "Escape leaves field before cancelling capture")
          keys.keyClick(Qt.Key_Escape)
          check(panel.windowOpened && !fake.capturing && fake.cancels === 1, "Escape cancels recording before closing")
          keys.keyClick(Qt.Key_Escape)
          check(!panel.windowOpened, "Next Escape closes the window")
          widget.open()
          check(panel.opened && !panel.windowOpened, "Bar popup remains available")
          editor.draftCombo = ["Y"]
          editor.draftAction = "SUPER+RETURN"
          panel.openWindow()
          check(!panel.opened && panel.windowOpened, "Open window replaces popup")
          check(editor.draftCombo[0] === "Y" && action.text === "SUPER+RETURN", "Shared draft survives reparenting")
          widget.open()
          editor.beginCapture()
          panel.openWindow()
          check(fake.capturing, "Window handoff preserves active capture")
          panel.close()
          check(!fake.capturing && !panel.windowOpened && !panel.opened && fake.cancels === 2, "Close releases capture exactly once")
          panel.close()
          check(fake.cancels === 2, "Closing inactive form leaves external pause alone")
          panel.openWindow()
          editor.beginCapture()
          widgetLoader.active = false
        } else if (stage === 4) {
          check(fake.capturing && panel.windowOpened && fake.cancels === 2, "Removing bar preserves independent window capture")
          check(panel.bar === null && panel.anchorItem === null && panel.hostWidget === null, "Removing bar clears its references")
          widgetLoader.active = true
          check(widget.panel === panel && fake.ensureEditor() === panel, "Restored bar reuses same service editor")
          panel.close()
          check(fake.cancels === 3, "Shared editor cancels its single recording")
          panel.openWindow()
          editor.Window.window.height = 300
        } else if (stage === 5) {
          // Wait for openWindow's fake list refresh, then fill the list.
          fake.bindings = Array(15).fill({combo: "A", keys: "RETURN"})
          editor.draftCombo = ["B"]
          editor.draftAction = "RETURN"
        } else if (stage === 6) {
          action.forceActiveFocus()
          keys.keyClick(Qt.Key_Tab)
        } else if (stage === 7) {
          var scroll = editor.parent.parent
          check(scroll.height < 300, "Small ordinary-window viewport is active")
          check(description.activeFocus && scroll.contentY > 0, "Tab scrolls to the lower description field")
          var point = description.mapToItem(scroll, 0, 0)
          check(point.y >= 0 && point.y + description.height <= scroll.height, "Focused description is fully visible")
          keys.keyClick(Qt.Key_Tab)
        } else if (stage === 8) {
          var scroll = editor.parent.parent
          var save = find(editor, function(item) { return item.text === "3. Save binding" })
          check(save.activeFocus, "Tab reaches Save")
          var point = save.mapToItem(scroll, 0, 0)
          check(point.y >= 0 && point.y + save.height <= scroll.height, "Focused Save is fully visible")
          // Preserve the merged editor's canonical identities and edit flags.
          fake.bindings = [
            {combo: "A", label: "B", keys: "RETURN", description: "repeat flag", repeat: true, hold: false, enabled: false},
            {combo: "X", exec: "true", description: "hold flag", repeat: false, hold: true}
          ]
          check(editor.comboText(["A"]) === "B", "Nintendo display labels remain separate from saved tokens")
          fake.comboCaptured(["A"])
          check(editor.draftRepeat && !editor.draftHold && editor.draftAction === "RETURN", "Capturing an existing combo preserves its action and flags")
          editor.saveDraft()
          editor.editBinding(fake.bindings[1])
          check(editor.draftHold && !editor.draftRepeat, "Editing preserves Hold")
          editor.saveDraft()
          check(editor._queue.length === 1, "The second edit queues behind the first")
        } else if (stage === 9) {
          check(editor._queue.length === 0 && editor.draftCombo.length === 0, "Both queued edits complete")
          check(fake.reloads === 0, "Queued mutations do not issue duplicate reloads")
          fake._handle(JSON.stringify({event: "error", message: "fixture config error"}))
          check(editor.lastError === "fixture config error", "Daemon errors reach the shared form")
          fake._handle(JSON.stringify({event: "fire", ok: false, label: "A", detail: "fixture action error"}))
          check(widget.flashFailed && widget.flashing, "Failed actions still pulse the bar red")
          editor.focusNavigation()
          editor.cursorIndex = -1
          keys.keyClick(Qt.Key_Down)
          check(editor.cursorIndex === 0, "Keyboard navigation selects a binding")
          keys.keyClick(Qt.Key_Return)
          check(editor.draftCombo[0] === "A" && editor.draftRepeat && action.activeFocus, "Enter edits the selected binding with flags")
          editor.runCli([fake.cli, "bind", "Z", "--keys", "RETURN"], false)
        } else if (stage === 10) {
          check(editor.statusMessage === "fixture mutation failed", "Failed CLI mutation is visible")
          check(editor.draftCombo[0] === "A", "Failed mutation preserves the current draft")
          editor.removeBinding("Y")
        } else if (stage === 11) {
          check(editor.statusMessage === "", "A later successful edit recovers")
          check(fake.reloads === 0 && editor.bindings === fake.bindings, "Daemon owns the binding snapshot and reload policy")
          panel.close()
          panel.openWindow()
          editor.clearDraft()
        } else if (stage === 12) {
          var record = find(editor, function(item) { return item.text === "1. Record combo" })
          check(record !== null && record.focusable, "Window buttons are focusable")
          record.forceActiveFocus()
          record.clicked()
          keys.keyClick(Qt.Key_Escape)
          check(!fake.capturing && panel.windowOpened, "Escape from a focused button cancels capture")
          keys.keyClick(Qt.Key_R)
          check(fake.capturing, "Record shortcut still works after clicking a button")
          keys.keyClick(Qt.Key_Escape)
          action.forceActiveFocus()
          keys.keyClick(Qt.Key_Backtab, Qt.ShiftModifier)
          check(!action.activeFocus, "Shift+Tab traverses backwards")
          keys.keyClick(Qt.Key_Tab)
          check(action.activeFocus, "Tab returns to the action field")
          editor.focusNavigation()
          editor.cursorIndex = -1
          var scroll = editor.parent.parent
          scroll.contentY = Math.min(160, scroll.contentHeight - scroll.height)
          savedScroll = scroll.contentY
          fake.lastError = "Resize without moving navigation focus"
        } else if (stage === 13) {
          var scroll = editor.parent.parent
          check(savedScroll > 0 && Math.abs(scroll.contentY - savedScroll) < 2, "Content resize does not jump to the full-height key catcher")
          editor.beginCapture()
          widget.togglePanel()
          check(panel.opened && !panel.windowOpened && fake.capturing, "Bar click hands the window into the popup without cancelling capture")
          var owner = panel.hostWidget
          var anchor = panel.anchorItem
          otherWidget.active = true
          otherWidget.item.settings = {hideWhenDisconnected: false}
          check(panel.hostWidget === owner && panel.anchorItem === anchor && !otherWidget.item.opened, "Passive second widget cannot steal an open popup")
          ipcClose.code = -1
          ipcClose.running = true
        } else if (stage === 14) {
          if (ipcClose.running || ipcClose.code < 0) return
          check(ipcClose.code === 0 && panel.opened && fake.capturing, "Real closeWindow IPC leaves a popup and recording alone: " + ipcClose.code + " / " + ipcClose.reply + " / " + panel.opened + " / " + fake.capturing)
          otherWidget.item.open()
          check(panel.hostWidget === otherWidget.item && otherWidget.item.opened && !widget.opened, "Explicit second-widget open transfers ownership")
          panel.openWindow()
          ipcClose.code = -1
          ipcClose.running = true
        } else if (stage === 15) {
          if (ipcClose.running || ipcClose.code < 0) return
          check(ipcClose.code === 0 && !panel.windowOpened && !fake.capturing, "Real closeWindow IPC closes just the window and cancels recording")
          ipcClose.method = "openWindow"
          ipcClose.code = -1
          ipcClose.running = true
        } else if (stage === 16) {
          if (ipcClose.running || ipcClose.code < 0) return
          check(ipcClose.code === 0 && panel.windowOpened && !panel.opened, "Real openWindow IPC opens the ordinary window")
          editor.beginCapture()
          if (Quickshell.env("CONTROLLER_TEST_SWAYSOCK")) compositorClose.running = true
          else editor.Window.window.close()
        } else if (stage === 17) {
          if (compositorClose.running) return
          check(!panel.windowOpened && !fake.capturing, "Window close event releases capture")
          fake.running = false
          panel.openWindow()
          check(panel.windowOpened, "Editor can reopen after a native window close")
          editor.setInputMode("game")
        } else if (stage === 18) {
          fake._handle(JSON.stringify({event:"bindings", modes:{enabled:true,active:"game"}, bindings:fake.bindings}))
          check(editor.configuredModesEnabled && editor.configuredMode === "game", "Game mode is explicit opt-in")
          var game = find(editor, function(item) { return item.objectName === "gameModeButton" })
          check(game.selected && !fake.running, "Saved choice is visible without starting a daemon")
          fake._handle(JSON.stringify({event:"state", modes_enabled:true, input_mode:"game", input_ready:true, input_status:"passthrough"}))
          fake.running = true
          check(fake.inputMode === "game" && editor.modeDescription.indexOf("available to games") >= 0, "Actual passthrough status is shown")
          editor.setInputMode("os")
        } else if (stage === 19) {
          fake._handle(JSON.stringify({event:"bindings", modes:{enabled:true,active:"os"}, bindings:fake.bindings}))
          check(editor.configuredModesEnabled && editor.configuredMode === "os", "OS mode choice saved")
          check(editor.modeDescription.indexOf("Switching") >= 0, "Requested OS choice does not claim ownership")
          fake._handle(JSON.stringify({event:"state", modes_enabled:true, input_mode:"os", input_ready:false, input_status:"waiting_grab"}))
          check(editor.modeDescription.indexOf("another client") >= 0, "Failed ownership is visible")
          fake._handle(JSON.stringify({event:"state", modes_enabled:true, input_mode:"os", input_ready:false, input_status:"waiting_neutral"}))
          check(editor.modeDescription.indexOf("center the sticks") >= 0, "Neutral guard is visible")
          editor.setInputMode("disable")
        } else if (stage === 20) {
          fake._handle(JSON.stringify({event:"bindings", modes:{enabled:false,active:"os"}, bindings:fake.bindings}))
          check(!editor.configuredModesEnabled && editor.bindings[0].combo === "A", "Turning modes off preserves saved assignments")
          fake.running = false
          console.log("EDITOR CHECK PASS")
          Qt.quit()
        }
        stage++
      } catch (e) {
        console.error("EDITOR CHECK FAIL: " + e)
        Qt.quit()
      }
    }
  }
}

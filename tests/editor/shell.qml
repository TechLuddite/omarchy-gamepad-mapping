import QtQuick
import QtQuick.Window
import Quickshell
import QtTest
import qs.Commons
import qs.Commons as Commons

ShellRoot {
  Service {
    id: fake
    running: true
    switchedOn: true
    bindings: [{combo: "A", label: "B", keys: "RETURN", repeat: true, hold: false, enabled: false}]
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
    property bool vertical: false
    property int barSize: 32
    property color barForeground: "#cacccc"
    property color urgent: "#ff0000"
    property string fontFamily: "monospace"
    property bool foregroundAnimationEnabled: false
    function hideTooltip(item) {}
  }
  Loader {
    id: widgetLoader
    active: false
    sourceComponent: Component { BarWidget { bar: fakeBar } }
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
      try {
        if (stage === 0) {
          check(fake.editor === null, "Checking bar state does not load editor")
          check(widget === null, "Launcher starts without any bar widget")
          panel = fake.ensureEditor()
          check(panel !== null && !panel.opened && !panel.windowOpened, "Editor starts closed")
          check(fake.ensureEditor() === panel, "IPC reuses one service editor")
          // The editor is reparented into the hidden popup initially.
          editor = find(panel, function(item) { return item.draftCombo !== undefined })
          check(editor !== null, "Shared content exists")
          action = find(editor, function(item) { return item.placeholderText !== undefined && item.placeholderText.indexOf("2. ") === 0 })
          description = find(editor, function(item) { return item.placeholderText === "Description (optional)" })
          check(action && description, "Manual key/command and description inputs retained")
          Commons.Color.shellValues = {"popups.text": "#64efab"}
          panel.openWindow()
        } else if (stage === 1) {
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
          editor.draftCombo = ["B"]
          editor.draftAction = "SUPER+"
          action.forceActiveFocus()
          keys.keyClick(Qt.Key_J)
          check(action.text === "SUPER+j", "Typing reaches manual input")
          keys.keyClick(Qt.Key_Tab)
          check(description.activeFocus, "Tab reaches description")
          editor.draftDescription = "custom keys"
          editor.saveDraft()
        } else if (stage === 2) {
          check(fake.reloads === 0 && editor.draftCombo.length === 0, "Saving clears draft without duplicate reload")
          editor.draftCombo = ["X"]
          editor.draftIsCommand = true
          editor.draftAction = "printf 'custom command'"
          editor.draftDescription = "custom command"
          editor.saveDraft()
        } else if (stage === 3) {
          check(fake.reloads === 0, "Manual command saved without duplicate reload")
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

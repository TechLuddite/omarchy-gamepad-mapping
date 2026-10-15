import QtQuick 6.11
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

// The bindings editor.
//
// The whole point of this panel is that you never have to look up what a
// button is called: press it on the pad and the combo is captured for you.
// The daemon is already streaming button events to Service.qml, so capture
// reuses that stream rather than opening the device a second time.
Ui.Panel {
  id: root
  moduleName: "co.klair.controller-control"
  ipcTarget: "co.klair.controller-control"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  readonly property color panelForeground: Color.popups.text
  readonly property var barIdentity: hostWidget || root

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")
  readonly property string cli: pluginDir + "bin/controller-control"

  readonly property bool connected: service ? service.connected === true : false
  readonly property string deviceName: service ? service.deviceName : ""
  readonly property var heldButtons: service ? service.heldButtons : []
  readonly property bool capturing: service ? service.capturing === true : false
  readonly property bool enabled: service ? service.enabled === true : true

  // Reads differently at each step, because "Record combo" on its own does
  // not tell you that the controller is what you are meant to press.
  readonly property string captureHint: {
    if (!connected) return "Connect a controller to record a combo."
    if (capturing) return "Press the buttons on your controller now, then let go. Bindings are muted while recording."
    if (draftCombo.length > 0) return "Captured " + comboText(draftCombo) + ". Now choose what it should do."
    return "Press Record, then press the buttons on your controller."
  }

  property var bindings: []
  property string configPath: ""
  property string layout: "auto"
  property string statusMessage: ""

  // ---- draft binding being composed -------------------------------------

  property var draftCombo: []
  property var shortcuts: []
  property var keyboardKeys: []
  property var externalMappings: []
  property bool mappingsChecked: false
  property string selectedKey: ""
  property string selectedShortcut: ""
  readonly property var draftAction: {
    for (var k = 0; k < keyboardKeys.length; k++)
      if (keyboardKeys[k].value === selectedKey) return keyboardKeys[k]
    for (var i = 0; i < shortcuts.length; i++)
      if (shortcuts[i].value === selectedShortcut) return shortcuts[i]
    return null
  }
  readonly property bool draftReady: draftCombo.length > 0 && draftAction !== null

  function mappingWarning(combo) {
    var warnings = []
    for (var i = 0; i < externalMappings.length; i++) {
      var m = externalMappings[i]
      if (combo.indexOf(m.token) !== -1)
        warnings.push(m.token + ": " + m.description + (m.modifiers ? " (with keyboard modifiers)" : ""))
    }
    return warnings.join("\n")
  }

  function open() {
    refresh()
    editorWindow.visible = false
    root.controller.show()
    editorWindow.visible = true
  }

  function close() {
    if (service) service.cancelCapture()
    root.controller.hide()
    editorWindow.visible = false
  }

  function toggle() {
    root.opened ? root.close() : root.open()
  }

  function refresh() {
    if (!listProc.running) listProc.running = true
    if (!shortcutProc.running) shortcutProc.running = true
    if (!keyboardProc.running) keyboardProc.running = true
    if (!mappingsProc.running) mappingsProc.running = true
  }

  function comboText(combo) {
    return combo.join(" + ")
  }

  function beginCapture() {
    if (!service) return
    root.statusMessage = ""
    root.draftCombo = []
    service.startCapture()
  }

  function saveDraft() {
    if (!root.draftReady) return
    var args = [root.cli, "bind", comboText(root.draftCombo)]
    args.push(root.draftAction.exec ? "--exec" : "--keys")
    args.push(root.draftAction.exec || root.draftAction.keys)
    if (root.draftAction.description) {
      args.push("--description")
      args.push(root.draftAction.description)
    }
    mutateProc.command = args
    mutateProc.running = true
  }

  function removeBinding(combo) {
    mutateProc.command = [root.cli, "unbind", combo]
    mutateProc.running = true
  }

  function clearDraft() {
    root.draftCombo = []
    root.selectedShortcut = ""
    root.selectedKey = ""
  }

  Connections {
    target: root.service
    enabled: root.service !== null
    function onComboCaptured(combo) {
      root.draftCombo = combo
    }
  }

  // ---- CLI calls ---------------------------------------------------------

  Process {
    id: mappingsProc
    command: [root.pluginDir + "bin/existing-mappings"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          root.externalMappings = result.bindings
          root.mappingsChecked = result.available === true
        } catch (e) { root.mappingsChecked = false }
      }
    }
  }

  Process {
    id: keyboardProc
    command: [root.pluginDir + "bin/keyboard-keys"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.keyboardKeys = JSON.parse(text) }
        catch (e) { root.statusMessage = "Could not read keyboard keys. Tap Reload to retry." }
      }
    }
  }

  Process {
    id: shortcutProc
    command: [root.pluginDir + "bin/omarchy-shortcuts", "list"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.shortcuts = JSON.parse(text) }
        catch (e) { root.statusMessage = "Could not read Omarchy shortcuts. Tap Reload to retry." }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim()) root.statusMessage = text.trim()
    }
  }

  Process {
    id: listProc
    command: [root.cli, "list", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var parsed = JSON.parse(text)
          root.bindings = Array.isArray(parsed.bindings) ? parsed.bindings : []
          root.layout = parsed.device && parsed.device.layout ? parsed.device.layout : "auto"
        } catch (e) {
          root.bindings = []
        }
      }
    }
  }

  Process {
    id: mutateProc
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text && text.trim() !== "") root.statusMessage = text.trim()
      }
    }
    onExited: function (exitCode) {
      if (exitCode === 0) {
        root.statusMessage = ""
        root.clearDraft()
        root.refresh()
        if (root.service) root.service.reload()
      }
    }
  }

  Process { id: openConfigProc }

  // An ordinary window allows the touchscreen keyboard to sit above the
  // editor. A full-screen Overlay popup otherwise catches keyboard taps.
  FloatingWindow {
    id: editorWindow
    title: "Gamepad Mapping"
    visible: false
    color: Color.popups.background
    implicitWidth: 820
    implicitHeight: 640
    onVisibleChanged: if (!visible && root.opened) root.close()

    Flickable {
      id: editorScroll
      anchors.fill: parent
      anchors.margins: Style.space(18)
      clip: true
      contentWidth: width
      contentHeight: content.implicitHeight
      boundsBehavior: Flickable.StopAtBounds

      ColumnLayout {
        id: content
        width: parent.width
        spacing: Style.space(10)

        // ---- status: device, live buttons, master switch, refresh --------

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Rectangle {
            width: Style.space(8)
            height: width
            radius: width / 2
            color: root.connected
              ? (root.enabled ? Color.accent : Qt.darker(root.panelForeground, 1.6))
              : Qt.darker(root.panelForeground, 2.2)
          }

          Text {
            Layout.fillWidth: true
            text: root.connected ? root.deviceName : "No controller connected"
            color: root.panelForeground
            elide: Text.ElideRight
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          // Whatever is held right now, sitting just before the controls so
          // you can watch the pad answer while your hands are on it.
          Row {
            spacing: Style.space(4)

            Repeater {
              model: root.heldButtons

              Rectangle {
                required property string modelData
                radius: Style.space(4)
                color: Style.selectedAccentFill
                implicitWidth: heldLabel.implicitWidth + Style.space(10)
                implicitHeight: heldLabel.implicitHeight + Style.space(4)

                Text {
                  id: heldLabel
                  anchors.centerIn: parent
                  text: parent.modelData
                  color: Color.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
              }
            }
          }

          Ui.ToggleSwitch {
            checked: root.enabled
            foreground: root.panelForeground
            onToggled: if (root.service) root.service.toggleEnabled()
          }

          Ui.PanelActionButton {
            iconText: "󰑐"
            tooltipText: "Reload bindings"
            foreground: root.panelForeground
            onClicked: {
              root.refresh()
              if (root.service) root.service.reload()
            }
          }
        }

        Ui.PanelSeparator {
          Layout.fillWidth: true
          foreground: root.panelForeground
        }

        // ---- existing bindings -------------------------------------------

        Ui.PanelSectionHeader {
          text: root.service && root.service.inputMode === "pointer" ? "POINTER MODE · OS BINDINGS SUPPRESSED" : root.service && !root.service.osMode ? "GAME MODE · OS BINDINGS SUPPRESSED" : root.service && root.service.modeSuppressed ? "OS MODE · WAITING FOR INPUT RELEASE" : root.enabled
            ? root.bindings.length + " BINDINGS"
            : root.bindings.length + " BINDINGS · DISABLED"
          foreground: root.enabled ? root.panelForeground : Color.urgent
        }

        Flickable {
          Layout.fillWidth: true
          Layout.preferredHeight: Math.min(bindingColumn.implicitHeight, Style.space(280))
          contentWidth: width
          contentHeight: bindingColumn.implicitHeight
          clip: true
          interactive: contentHeight > height
          opacity: root.enabled ? 1.0 : 0.45

          ColumnLayout {
            id: bindingColumn
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.bindings

              RowLayout {
                id: bindingRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(8)

                readonly property string actionText: bindingRow.modelData.keys
                  ? bindingRow.modelData.keys
                  : (bindingRow.modelData.exec || "")
                readonly property bool isCommand: !bindingRow.modelData.keys

                Text {
                  Layout.preferredWidth: Style.space(112)
                  Layout.alignment: Qt.AlignTop
                  text: bindingRow.modelData.combo
                  color: Color.accent
                  elide: Text.ElideRight
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                // Description on top, what it actually does underneath --
                // a description alone does not tell you which shortcut it
                // sends, which is the thing you need when editing.
                ColumnLayout {
                  Layout.fillWidth: true
                  spacing: 0

                  Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: bindingRow.modelData.description || ""
                    color: root.panelForeground
                    elide: Text.ElideRight
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    Layout.fillWidth: true
                    text: (bindingRow.isCommand ? "$ " : "") + bindingRow.actionText
                      + (bindingRow.modelData.repeat ? "  ·  repeat" : "")
                      + (bindingRow.modelData.hold ? "  ·  hold" : "")
                    color: Qt.darker(root.panelForeground, 1.6)
                    elide: Text.ElideRight
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    Layout.fillWidth: true
                    text: root.mappingWarning(bindingRow.modelData.combo.split(/\s*\+\s*/))
                    visible: text !== ""
                    color: Color.urgent
                    wrapMode: Text.WordWrap
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }

                Ui.PanelActionButton {
                  Layout.alignment: Qt.AlignTop
                  iconText: "󰆴"
                  tooltipText: "Remove binding"
                  foreground: root.panelForeground
                  hoverColor: Color.urgent
                  onClicked: root.removeBinding(bindingRow.modelData.combo)
                }
              }
            }
          }
        }

        Ui.PanelSeparator {
          Layout.fillWidth: true
          foreground: root.panelForeground
        }

        // ---- new binding --------------------------------------------------

        Ui.PanelSectionHeader {
          text: "EXISTING OS MAPPINGS · READ ONLY"
          foreground: root.panelForeground
        }
        Text {
          Layout.fillWidth: true
          text: root.mappingsChecked ? "Mappings outside this plugin are shown below. Native pointer navigation also depends on per-device settings; volume and power retain their OS bindings." : "Could not check existing OS mappings. Tap Reload to retry."
          color: root.panelForeground
          wrapMode: Text.WordWrap
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
        Repeater {
          model: root.externalMappings
          Text {
            required property var modelData
            Layout.fillWidth: true
            text: modelData.token + " · " + modelData.description + (modelData.modifiers ? " · keyboard modifiers " + modelData.modifiers : "")
            color: root.panelForeground
            wrapMode: Text.WordWrap
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        Ui.PanelSectionHeader {
          text: "NEW BINDING"
          foreground: root.panelForeground
        }

        // Step 1 of the flow, spelled out: the pad is the input device for
        // this form, and that is not obvious from a button labelled "Record".
        Text {
          Layout.fillWidth: true
          text: root.captureHint
          color: root.capturing ? Color.accent : Qt.darker(root.panelForeground, 1.5)
          wrapMode: Text.WordWrap
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Ui.Button {
            text: root.capturing
              ? "Waiting…"
              : (root.draftCombo.length > 0
                  ? root.comboText(root.draftCombo)
                  : "1. Record combo")
            enabled: root.connected
            selected: root.capturing || root.draftCombo.length > 0
            bordered: true
            focusable: true
            foreground: root.panelForeground
            onClicked: root.beginCapture()
          }

        }

        ShortcutDropdown {
          id: shortcutPicker
          Layout.fillWidth: true
          foreground: root.panelForeground
          label: "2. Choose an Omarchy shortcut"
          placeholderText: "Search actions or keys…"
          emptyText: "No matching shortcuts"
          rowHeight: Style.space(44)
          popupRowHeight: Style.space(44)
          value: root.selectedShortcut
          options: [{ value: "", label: root.shortcuts.length > 0 ? "Select an action…" : "Loading Omarchy shortcuts…" }].concat(root.shortcuts)
          onChanged: function(value) {
            root.selectedShortcut = value
            root.selectedKey = ""
            // Restore the binding after Dropdown writes its selected value,
            // so Save/Clear also reset the displayed selection.
            shortcutPicker.value = Qt.binding(function() { return root.selectedShortcut })
          }
        }

        ShortcutDropdown {
          id: keyboardPicker
          Layout.fillWidth: true
          foreground: root.panelForeground
          label: "Or choose a standard keyboard key"
          placeholderText: "Search keyboard keys…"
          rowHeight: Style.space(44)
          popupRowHeight: Style.space(44)
          value: root.selectedKey
          options: [{ value: "", label: "Select a keyboard key…" }].concat(root.keyboardKeys)
          onChanged: function(value) {
            root.selectedKey = value
            root.selectedShortcut = ""
            keyboardPicker.value = Qt.binding(function() { return root.selectedKey })
          }
        }

        Text {
          Layout.fillWidth: true
          text: root.mappingWarning(root.draftCombo)
          visible: text !== ""
          color: Color.urgent
          wrapMode: Text.WordWrap
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Ui.Button {
            text: "3. Save binding"
            enabled: root.draftReady
            bordered: true
            focusable: true
            foreground: root.panelForeground
            onClicked: root.saveDraft()
          }

          Item { Layout.fillWidth: true }

          Ui.Button {
            text: "Clear"
            bordered: true
            focusable: true
            foreground: root.panelForeground
            onClicked: {
              if (root.service) root.service.cancelCapture()
              root.clearDraft()
            }
          }
        }

        Text {
          Layout.fillWidth: true
          visible: root.statusMessage !== ""
          text: root.statusMessage
          color: Color.urgent
          wrapMode: Text.WordWrap
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}

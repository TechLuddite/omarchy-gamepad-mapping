import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The bindings editor.
//
// The whole point of this panel is that you never have to look up what a
// button is called: press it on the pad and the combo is captured for you.
// The daemon is already streaming button events to Service.qml, so capture
// reuses that stream rather than opening the device a second time.
Panel {
  id: root
  moduleName: "co.klair.controller-control"
  ipcTarget: "co.klair.controller-control"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
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
  property bool draftIsCommand: false
  readonly property bool draftReady: draftCombo.length > 0 && actionField.text.trim() !== ""

  function open() {
    refresh()
    root.controller.show()
  }

  function close() {
    if (service) service.cancelCapture()
    root.controller.hide()
  }

  function toggle() {
    root.opened ? root.close() : root.open()
  }

  function refresh() {
    if (!listProc.running) listProc.running = true
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
    args.push(root.draftIsCommand ? "--exec" : "--keys")
    args.push(actionField.text.trim())
    if (descriptionField.text.trim() !== "") {
      args.push("--description")
      args.push(descriptionField.text.trim())
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
    actionField.text = ""
    descriptionField.text = ""
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

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(470))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

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
              ? (root.enabled ? Color.accent : Qt.darker(root.barForeground, 1.6))
              : Qt.darker(root.barForeground, 2.2)
          }

          Text {
            Layout.fillWidth: true
            text: root.connected ? root.deviceName : "No controller connected"
            color: root.barForeground
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

          ToggleSwitch {
            checked: root.enabled
            foreground: root.barForeground
            onToggled: if (root.service) root.service.toggleEnabled()
          }

          PanelActionButton {
            iconText: "󰑐"
            tooltipText: "Reload bindings"
            foreground: root.barForeground
            onClicked: {
              root.refresh()
              if (root.service) root.service.reload()
            }
          }
        }

        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.barForeground
        }

        // ---- existing bindings -------------------------------------------

        PanelSectionHeader {
          text: root.enabled
            ? root.bindings.length + " BINDINGS"
            : root.bindings.length + " BINDINGS · DISABLED"
          foreground: root.enabled ? root.barForeground : Color.urgent
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
                    color: root.barForeground
                    elide: Text.ElideRight
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    Layout.fillWidth: true
                    text: (bindingRow.isCommand ? "$ " : "") + bindingRow.actionText
                      + (bindingRow.modelData.repeat ? "  ·  repeat" : "")
                      + (bindingRow.modelData.hold ? "  ·  hold" : "")
                    color: Qt.darker(root.barForeground, 1.6)
                    elide: Text.ElideRight
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }

                PanelActionButton {
                  Layout.alignment: Qt.AlignTop
                  iconText: "󰆴"
                  tooltipText: "Remove binding"
                  foreground: root.barForeground
                  hoverColor: Color.urgent
                  onClicked: root.removeBinding(bindingRow.modelData.combo)
                }
              }
            }
          }
        }

        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.barForeground
        }

        // ---- new binding --------------------------------------------------

        PanelSectionHeader {
          text: "NEW BINDING"
          foreground: root.barForeground
        }

        // Step 1 of the flow, spelled out: the pad is the input device for
        // this form, and that is not obvious from a button labelled "Record".
        Text {
          Layout.fillWidth: true
          text: root.captureHint
          color: root.capturing ? Color.accent : Qt.darker(root.barForeground, 1.5)
          wrapMode: Text.WordWrap
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Button {
            text: root.capturing
              ? "Waiting…"
              : (root.draftCombo.length > 0
                  ? root.comboText(root.draftCombo)
                  : "1. Record combo")
            enabled: root.connected
            selected: root.capturing || root.draftCombo.length > 0
            bordered: true
            foreground: root.barForeground
            onClicked: root.beginCapture()
          }

          Button {
            text: root.draftIsCommand ? "Command" : "Keys"
            tooltipText: root.draftIsCommand
              ? "Runs a shell command"
              : "Types a keyboard shortcut, e.g. SUPER+RETURN"
            bordered: true
            foreground: root.barForeground
            onClicked: root.draftIsCommand = !root.draftIsCommand
          }
        }

        TextField {
          id: actionField
          Layout.fillWidth: true
          foreground: root.barForeground
          placeholderText: root.draftIsCommand
            ? "2. Command to run, e.g. omarchy capture screenshot"
            : "2. Keys to send, e.g. SUPER+RETURN"
          onAccepted: root.saveDraft()
        }

        TextField {
          id: descriptionField
          Layout.fillWidth: true
          foreground: root.barForeground
          placeholderText: "Description (optional)"
          onAccepted: root.saveDraft()
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Button {
            text: "3. Save binding"
            enabled: root.draftReady
            bordered: true
            foreground: root.barForeground
            onClicked: root.saveDraft()
          }

          Item { Layout.fillWidth: true }

          Button {
            text: "Clear"
            bordered: true
            foreground: root.barForeground
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

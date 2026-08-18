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
    contentWidth: panel.fittedContentWidth(Style.space(460))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      ColumnLayout {
        id: content
        width: parent.width
        spacing: Style.space(10)

        // ---- status ------------------------------------------------------

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Rectangle {
            width: Style.space(8)
            height: width
            radius: width / 2
            color: root.connected ? Color.accent : Qt.darker(root.barForeground, 2.2)
          }

          Text {
            Layout.fillWidth: true
            text: root.connected ? root.deviceName : "No controller connected"
            color: root.barForeground
            elide: Text.ElideRight
            font.family: Style.font.family
            font.pixelSize: Style.font.body
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

        // ---- live buttons ------------------------------------------------

        Flow {
          Layout.fillWidth: true
          spacing: Style.space(6)
          visible: root.heldButtons.length > 0

          Repeater {
            model: root.heldButtons

            Rectangle {
              required property string modelData
              radius: Style.space(4)
              color: Style.selectedAccentFill
              implicitWidth: heldLabel.implicitWidth + Style.space(12)
              implicitHeight: heldLabel.implicitHeight + Style.space(6)

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

        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.barForeground
        }

        // ---- existing bindings -------------------------------------------

        PanelSectionHeader {
          text: root.bindings.length + " BINDINGS"
          foreground: root.barForeground
        }

        Flickable {
          Layout.fillWidth: true
          Layout.preferredHeight: Math.min(bindingColumn.implicitHeight, Style.space(260))
          contentWidth: width
          contentHeight: bindingColumn.implicitHeight
          clip: true
          interactive: contentHeight > height

          ColumnLayout {
            id: bindingColumn
            width: parent.width
            spacing: Style.space(2)

            Repeater {
              model: root.bindings

              RowLayout {
                id: bindingRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(8)

                Text {
                  Layout.preferredWidth: Style.space(120)
                  text: bindingRow.modelData.combo
                  color: Color.accent
                  elide: Text.ElideRight
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                Text {
                  Layout.fillWidth: true
                  text: bindingRow.modelData.description
                    && bindingRow.modelData.description !== ""
                    ? bindingRow.modelData.description
                    : (bindingRow.modelData.keys || bindingRow.modelData.exec || "")
                  color: root.barForeground
                  elide: Text.ElideRight
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                }

                PanelActionButton {
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

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Button {
            text: root.capturing
              ? "Press a combo…"
              : (root.draftCombo.length > 0 ? root.comboText(root.draftCombo) : "Record combo")
            enabled: root.connected
            selected: root.capturing
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
          placeholderText: root.draftIsCommand ? "omarchy capture screenshot" : "SUPER+RETURN"
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
            text: "Save binding"
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

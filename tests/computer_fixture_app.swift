// Minimal AppKit window used to prove the observe -> guard -> act -> verify loop.
// Build: swiftc -O -o /tmp/macjev-fixture-app tests/computer_fixture_app.swift

import AppKit

final class FixtureController: NSObject {
    var window: NSWindow!
    var counter = 0
    let counterLabel = NSTextField(labelWithString: "count=0")
    let input = NSTextField(string: "")

    func build() {
        let frame = NSRect(x: 200, y: 200, width: 520, height: 260)
        window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "MacJev Computer Fixture"
        let content = NSView(frame: frame)

        let button = NSButton(title: "Increment", target: self, action: #selector(increment))
        button.frame = NSRect(x: 30, y: 170, width: 140, height: 36)
        button.setAccessibilityIdentifier("fixture-increment")
        content.addSubview(button)

        counterLabel.frame = NSRect(x: 190, y: 176, width: 200, height: 24)
        counterLabel.setAccessibilityIdentifier("fixture-counter")
        content.addSubview(counterLabel)

        input.frame = NSRect(x: 30, y: 100, width: 300, height: 28)
        input.setAccessibilityIdentifier("fixture-input")
        content.addSubview(input)

        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
    }

    @objc func increment() {
        counter += 1
        counterLabel.stringValue = "count=\(counter)"
    }
}

let application = NSApplication.shared
application.setActivationPolicy(.regular)
let controller = FixtureController()
controller.build()
application.activate(ignoringOtherApps: true)
application.run()

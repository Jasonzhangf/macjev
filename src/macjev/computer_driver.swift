import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit
import Foundation
import ScreenCaptureKit

struct DriverError: Error {
    let code: String
    let message: String
}

struct PointValue: Codable {
    let x: Double
    let y: Double
}

struct SizeValue: Codable {
    let width: Double
    let height: Double
}

struct RectValue: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct WindowValue: Codable {
    let window_id: UInt32
    let pid: Int32
    let application_id: String
    let application_name: String
    let title: String
    let layer: Int
    let on_screen: Bool
    let bounds: RectValue
}

struct ElementValue: Codable {
    let element_id: String
    let element_chain: String
    let parent_id: String?
    let depth: Int
    let role: String
    let subrole: String?
    let title: String?
    let description: String?
    let value: String?
    let identifier: String?
    let enabled: Bool?
    let focused: Bool?
    let selected: Bool?
    let settable: Bool?
    let position: PointValue?
    let size: SizeValue?
    let actions: [String]
}

struct ObserveResult: Codable {
    let window: WindowValue
    let revision: String
    let visual_digest: String
    let elements: [ElementValue]
    let truncated: Bool
    let screenshot_path: String
    let screenshot_width: Int
    let screenshot_height: Int
    let screenshot_scale: Double
    /// How the web-content accessibility wake-up resolved for this window:
    /// `enabled`, `already_enabled`, `not_settable`, or `write_failed:<code>`.
    let accessibility: String
    let timings_ms: [String: Double]
}

struct ActResult: Codable {
    let action: String
    let element_id: String?
    let point: PointValue?
    let performed: Bool
}

/// Result of a raw input action (mouse primitive or keyboard event).
struct InputResult: Codable {
    let action: String
    let point: PointValue?
    let from: PointValue?
    let to: PointValue?
    let button: String?
    let count: Int?
    let text: String?
    let key: String?
    let modifiers: [String]?
    let events: Int
    let performed: Bool
    /// Identity of the element that held keyboard focus when the input was
    /// posted. Present only for keyboard operations, which are pointless to
    /// report without it.
    var focus: String?
}

struct HitTestResult: Codable {
    let point: PointValue
    let element_id: String
    let element_path: String?
    let role: String
    let title: String?
    let description: String?
    let value: String?
    let position: PointValue?
    let size: SizeValue?
    let child_count: Int
    let parent_chain: [String]
    let actions: [String]
}

func jsonData<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    return try encoder.encode(value)
}

func writeJSON<T: Encodable>(_ value: T) throws {
    FileHandle.standardOutput.write(try jsonData(value))
    FileHandle.standardOutput.write(Data([0x0a]))
}

func fail(_ code: String, _ message: String) -> Never {
    let object: [String: Any] = ["error": ["code": code, "message": message]]
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([0x0a]))
    }
    exit(2)
}

func argument(_ name: String) -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: name) else {
        return nil
    }
    let valueIndex = CommandLine.arguments.index(after: index)
    guard valueIndex < CommandLine.arguments.endIndex else {
        return nil
    }
    return CommandLine.arguments[valueIndex]
}

func stringAttribute(_ element: AXUIElement, _ name: CFString) -> String? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name, &value) == .success else {
        return nil
    }
    if let text = value as? String {
        return text
    }
    if let number = value as? NSNumber {
        return number.stringValue
    }
    return nil
}

func boolAttribute(_ element: AXUIElement, _ name: CFString) -> Bool? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name, &value) == .success else {
        return nil
    }
    return value as? Bool
}

func isSettable(_ element: AXUIElement, _ name: CFString) -> Bool? {
    var settable = DarwinBoolean(false)
    guard AXUIElementIsAttributeSettable(element, name, &settable) == .success else {
        return nil
    }
    return settable.boolValue
}

func pointAttribute(_ element: AXUIElement, _ name: CFString) -> CGPoint? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name, &value) == .success,
          let axValue = value,
          CFGetTypeID(axValue) == AXValueGetTypeID()
    else {
        return nil
    }
    var point = CGPoint.zero
    guard AXValueGetValue(axValue as! AXValue, .cgPoint, &point) else {
        return nil
    }
    return point
}

func sizeAttribute(_ element: AXUIElement, _ name: CFString) -> CGSize? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name, &value) == .success,
          let axValue = value,
          CFGetTypeID(axValue) == AXValueGetTypeID()
    else {
        return nil
    }
    var size = CGSize.zero
    guard AXValueGetValue(axValue as! AXValue, .cgSize, &size) else {
        return nil
    }
    return size
}

func encodeChain(_ chain: [Int]) -> String {
    chain.isEmpty ? "root" : chain.map(String.init).joined(separator: ".")
}

/// Identity is derived from the anchor-rooted sibling chain and the element's
/// stable attributes, never from pointer identity or geometry, so it survives
/// a fresh observation of the same tree.
func elementIdentifier(
    _ element: AXUIElement,
    chain: [Int]?
) -> String {
    let path = chain.map(encodeChain) ?? "unrooted"
    let identity = [
        path,
        stringAttribute(element, kAXRoleAttribute as CFString) ?? "",
        stringAttribute(element, kAXSubroleAttribute as CFString) ?? "",
        stringAttribute(element, kAXTitleAttribute as CFString) ?? "",
        stringAttribute(element, kAXIdentifierAttribute as CFString) ?? "",
    ].joined(separator: "\u{1f}")
    return "sha256:" + sha256(Data(identity.utf8)).prefix(32)
}

/// Sibling-index chain from the window root to `element`.
func positionChain(_ element: AXUIElement, root: AXUIElement) -> [Int] {
    if CFEqual(element, root) {
        return []
    }
    var chain: [Int] = []
    var current = element
    for _ in 0..<128 {
        guard let parent = elementParent(current) else {
            break
        }
        let siblings = elementChildren(parent)
        let index = siblings.firstIndex(where: { CFEqual($0, current) }) ?? siblings.count
        chain.append(index)
        if CFEqual(parent, root) {
            return chain.reversed()
        }
        current = parent
    }
    return chain.reversed()
}

func elementActions(_ element: AXUIElement) -> [String] {
    var actions: CFArray?
    guard AXUIElementCopyActionNames(element, &actions) == .success,
          let values = actions as? [String]
    else {
        return []
    }
    return values
}

func elementChildren(_ element: AXUIElement) -> [AXUIElement] {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        element,
        kAXChildrenAttribute as CFString,
        &value
    ) == .success,
          let children = value as? [AXUIElement]
    else {
        return []
    }
    return children
}

func copyElementAttribute(
    _ element: AXUIElement,
    _ name: CFString
) -> AXUIElement? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name, &value) == .success,
          let found = value,
          CFGetTypeID(found) == AXUIElementGetTypeID()
    else {
        return nil
    }
    return (found as! AXUIElement)
}

func elementParent(_ element: AXUIElement) -> AXUIElement? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        element,
        kAXParentAttribute as CFString,
        &value
    ) == .success,
          let parent = value,
          CFGetTypeID(parent) == AXUIElementGetTypeID()
    else {
        return nil
    }
    return (parent as! AXUIElement)
}

func walkElement(
    _ element: AXUIElement,
    root: AXUIElement,
    chain: [Int],
    parentID: String?,
    depth: Int,
    maximumDepth: Int,
    maximumElements: Int,
    output: inout [ElementValue]
) -> Bool {
    if output.count >= maximumElements {
        return true
    }
    let position = pointAttribute(element, kAXPositionAttribute as CFString)
    let size = sizeAttribute(element, kAXSizeAttribute as CFString)
    let identifier = elementIdentifier(element, chain: chain)
    output.append(
        ElementValue(
            element_id: identifier,
            element_chain: encodeChain(chain),
            parent_id: parentID,
            depth: depth,
            role: stringAttribute(element, kAXRoleAttribute as CFString) ?? "AXUnknown",
            subrole: stringAttribute(element, kAXSubroleAttribute as CFString),
            title: stringAttribute(element, kAXTitleAttribute as CFString),
            description: stringAttribute(element, kAXDescriptionAttribute as CFString),
            value: stringAttribute(element, kAXValueAttribute as CFString),
            identifier: stringAttribute(element, kAXIdentifierAttribute as CFString),
            enabled: boolAttribute(element, kAXEnabledAttribute as CFString),
            focused: boolAttribute(element, kAXFocusedAttribute as CFString),
            selected: boolAttribute(element, kAXSelectedAttribute as CFString),
            settable: isSettable(element, kAXValueAttribute as CFString),
            position: position.map { PointValue(x: $0.x, y: $0.y) },
            size: size.map { SizeValue(width: $0.width, height: $0.height) },
            actions: elementActions(element)
        )
    )
    if depth >= maximumDepth {
        return output.count >= maximumElements
    }
    for (index, child) in elementChildren(element).enumerated() {
        if walkElement(
            child,
            root: root,
            chain: chain + [index],
            parentID: identifier,
            depth: depth + 1,
            maximumDepth: maximumDepth,
            maximumElements: maximumElements,
            output: &output
        ) {
            return true
        }
    }
    return false
}

func applicationElement(pid: pid_t) -> AXUIElement {
    AXUIElementCreateApplication(pid)
}

func windowsForApplication(_ application: AXUIElement) -> [AXUIElement] {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        application,
        kAXWindowsAttribute as CFString,
        &value
    ) == .success,
          let windows = value as? [AXUIElement]
    else {
        return []
    }
    return windows
}

func windowNumber(_ window: AXUIElement) -> UInt32? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        window,
        "AXWindowNumber" as CFString,
        &value
    ) == .success,
          let number = value as? NSNumber
    else {
        return nil
    }
    return number.uint32Value
}

func applicationWindows() -> [(NSRunningApplication, UInt32, AXUIElement)] {
    var results: [(NSRunningApplication, UInt32, AXUIElement)] = []
    for application in NSWorkspace.shared.runningApplications {
        guard application.activationPolicy != .prohibited else {
            continue
        }
        let axApplication = applicationElement(pid: application.processIdentifier)
        for window in windowsForApplication(axApplication) {
            if let number = windowNumber(window) {
                results.append((application, number, window))
            }
        }
    }
    return results
}

func windowInfo() -> [WindowValue] {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        as? [[String: Any]]
    else {
        return []
    }
    var values: [WindowValue] = []
    for item in raw {
        guard let number = item[kCGWindowNumber as String] as? NSNumber,
              let pid = item[kCGWindowOwnerPID as String] as? NSNumber,
              let bounds = item[kCGWindowBounds as String] as? [String: Any]
        else {
            continue
        }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let width = (bounds["Width"] as? NSNumber)?.doubleValue ?? 0
        let height = (bounds["Height"] as? NSNumber)?.doubleValue ?? 0
        let running = NSRunningApplication(processIdentifier: pid.int32Value)
        values.append(
            WindowValue(
                window_id: number.uint32Value,
                pid: pid.int32Value,
                application_id: running?.bundleIdentifier ?? "",
                application_name: running?.localizedName ?? "",
                title: item[kCGWindowName as String] as? String ?? "",
                layer: (item[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0,
                on_screen: (item[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue ?? false,
                bounds: RectValue(x: x, y: y, width: width, height: height)
            )
        )
    }
    return values.sorted {
        if $0.application_name == $1.application_name {
            return $0.window_id < $1.window_id
        }
        return $0.application_name < $1.application_name
    }
}

func selectWindow(_ identifier: String) throws -> WindowValue {
    let values = windowInfo()
    if let number = UInt32(identifier),
       let exact = values.first(where: { $0.window_id == number }) {
        return exact
    }
    if let exact = values.first(where: { $0.application_id == identifier }) {
        return exact
    }
    if let exact = values.first(where: { $0.application_name == identifier }) {
        return exact
    }
    throw DriverError(code: "window_not_found", message: "no window matched \(identifier)")
}

func selectAXWindow(_ value: WindowValue) -> AXUIElement {
    let application = applicationElement(pid: value.pid)
    let windows = windowsForApplication(application)
    for window in windows {
        if windowNumber(window) == value.window_id {
            return window
        }
    }
    // AXWindowNumber is not exposed by every application; fall back to the
    // window whose title and frame match the captured CGWindow record.
    let matchingTitle = windows.filter {
        stringAttribute($0, kAXTitleAttribute as CFString) == value.title
    }
    if matchingTitle.count == 1 {
        return matchingTitle[0]
    }
    for window in matchingTitle.isEmpty ? windows : matchingTitle {
        guard let position = pointAttribute(window, kAXPositionAttribute as CFString),
              let size = sizeAttribute(window, kAXSizeAttribute as CFString)
        else {
            continue
        }
        if abs(position.x - value.bounds.x) < 2,
           abs(position.y - value.bounds.y) < 2,
           abs(size.width - value.bounds.width) < 2,
           abs(size.height - value.bounds.height) < 2 {
            return window
        }
    }
    return application
}

/// Whether the running application hosts a Chromium-derived renderer.
///
/// Tree shape cannot answer this: a dormant Chromium renderer and an ordinary
/// AppKit window both present a shallow chain of unlabeled groups.
///
/// The reliable signal is the live process tree. Every Chromium-derived app
/// runs a renderer helper as a direct child under a bundle-specific name
/// (`Obsidian Helper (Renderer)`, `Codex (Renderer)`, `QQ Helper (Renderer)`),
/// and no native app does. Bundle layout cannot be used instead: ChatGPT nests
/// its helper inside its own framework, and QQNT ships no Chromium-named
/// framework at all.
func hostsWebRenderer(pid: pid_t) -> Bool {
    let children = childProcessIDs(of: pid)
    guard !children.isEmpty else {
        return false
    }
    for child in children {
        var buffer = [CChar](repeating: 0, count: 4096)
        guard proc_name(child, &buffer, UInt32(buffer.count)) > 0 else {
            continue
        }
        if String(cString: buffer).lowercased().contains("renderer") {
            return true
        }
    }
    return false
}

/// Direct child process IDs of `pid`, or an empty list when unavailable.
func childProcessIDs(of pid: pid_t) -> [pid_t] {
    var buffer = [pid_t](repeating: 0, count: 4096)
    let count = proc_listchildpids(
        pid,
        &buffer,
        Int32(buffer.count * MemoryLayout<pid_t>.size)
    )
    guard count > 0 else {
        return []
    }
    return Array(buffer.prefix(Int(count)))
}

/// Force Chromium-derived applications (Electron, Tauri, CEF) to publish their
/// web content into the accessibility tree.
///
/// Chromium builds the AX tree lazily: it stays dormant until an assistive
/// client announces itself, so a plain AX walk sees only the native window
/// frame plus a handful of wrapper nodes. `AXEnhancedUserInterface` is the
/// switch those applications listen for, and Apple documents it as 0/1.
///
/// Every AppKit application exposes the same attribute, so writing it blindly
/// would flip a rendering hint on apps that never asked for one. The wake-up is
/// therefore conditional on the bundle actually hosting a web renderer.
///
/// The attribute is application-scoped and survives across processes, so once a
/// renderer is awake later observations report `already_enabled`.
func enableWebAccessibility(pid: pid_t) -> String {
    guard hostsWebRenderer(pid: pid) else {
        return "not_applicable"
    }
    let application = applicationElement(pid: pid)
    let name = "AXEnhancedUserInterface" as CFString
    var current: CFTypeRef?
    let readStatus = AXUIElementCopyAttributeValue(application, name, &current)
    guard readStatus == .success else {
        return "unsupported"
    }
    if let value = current as? Bool, value {
        return "already_enabled"
    }

    let write = AXUIElementSetAttributeValue(application, name, kCFBooleanTrue)
    // The renderer publishes asynchronously, so re-read rather than trusting the
    // write status. Chromium returns `-25208` even for writes that do land, so
    // the confirmed value is the only trustworthy signal.
    usleep(400_000)
    var confirmed: CFTypeRef?
    let confirmStatus = AXUIElementCopyAttributeValue(application, name, &confirmed)
    if confirmStatus == .success, let value = confirmed as? Bool, value {
        return "enabled"
    }
    return "write_failed:\(write.rawValue)"
}

/// `window` is the identity anchor used by `observe`; `node` is the cursor.
func findElement(
    _ node: AXUIElement,
    root window: AXUIElement,
    chain: [Int],
    identifier: String
) -> AXUIElement? {
    if elementIdentifier(node, chain: chain) == identifier {
        return node
    }
    for (index, child) in elementChildren(node).enumerated() {
        if let found = findElement(
            child,
            root: window,
            chain: chain + [index],
            identifier: identifier
        ) {
            return found
        }
    }
    return nil
}

func ancestorChain(_ element: AXUIElement, root: AXUIElement) -> [String] {
    var chain: [String] = []
    var current = element
    for _ in 0..<128 {
        if CFEqual(current, root) {
            break
        }
        let attribution = [
            stringAttribute(current, kAXRoleAttribute as CFString) ?? "AXUnknown",
            stringAttribute(current, kAXTitleAttribute as CFString) ?? "",
            stringAttribute(current, kAXValueAttribute as CFString).map {
                String($0.prefix(40))
            } ?? "",
        ].filter { !$0.isEmpty }.joined(separator: ":")
        chain.append(attribution)
        guard let parent = elementParent(current) else {
            break
        }
        current = parent
    }
    return chain.reversed()
}

func screenshot(_ window: WindowValue, outputPath: String) async throws -> (Int, Int, Double) {
    let content = try await SCShareableContent.excludingDesktopWindows(
        false,
        onScreenWindowsOnly: true
    )
    guard let shareable = content.windows.first(where: { $0.windowID == window.window_id }) else {
        throw DriverError(
            code: "window_not_capturable",
            message: "window \(window.window_id) is not available to ScreenCaptureKit"
        )
    }
    let filter = SCContentFilter(desktopIndependentWindow: shareable)
    let configuration = SCStreamConfiguration()
    configuration.width = Int(shareable.frame.width)
    configuration.height = Int(shareable.frame.height)
    configuration.showsCursor = false
    configuration.capturesAudio = false
    configuration.preservesAspectRatio = true
    let image = try await SCScreenshotManager.captureImage(
        contentFilter: filter,
        configuration: configuration
    )
    let bitmap = NSBitmapImageRep(cgImage: image)
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw DriverError(code: "screenshot_encode_failed", message: "cannot encode PNG")
    }
    try png.write(to: URL(fileURLWithPath: outputPath), options: .atomic)
    let scale = Double(image.width) / max(shareable.frame.width, 1)
    return (image.width, image.height, scale)
}

func performAXAction(_ element: AXUIElement, action: String) throws {
    let status = AXUIElementPerformAction(element, action as CFString)
    if status != .success {
        throw DriverError(
            code: "ax_action_failed",
            message: "AX action \(action) failed with status \(status.rawValue)"
        )
    }
}

func mouseEvent(_ type: CGEventType, point: CGPoint) throws {
    guard let event = CGEvent(
        mouseEventSource: nil,
        mouseType: type,
        mouseCursorPosition: point,
        mouseButton: .left
    ) else {
        throw DriverError(code: "mouse_event_failed", message: "cannot create mouse event")
    }
    event.post(tap: .cghidEventTap)
}

func performPointClick(_ point: PointValue) throws {
    let value = CGPoint(x: point.x, y: point.y)
    try mouseEvent(.mouseMoved, point: value)
    try mouseEvent(.leftMouseDown, point: value)
    try mouseEvent(.leftMouseUp, point: value)
}

/// Raw input targets a window, so a point outside it is a caller bug rather
/// than something to clamp silently.
func requirePointInside(_ point: PointValue, window: WindowValue) throws {
    guard point.x >= window.bounds.x,
          point.y >= window.bounds.y,
          point.x <= window.bounds.x + window.bounds.width,
          point.y <= window.bounds.y + window.bounds.height
    else {
        throw DriverError(
            code: "point_outside_window",
            message: "\(point.x),\(point.y) is outside window \(window.window_id)"
        )
    }
}

// MARK: - Synthetic input primitives

let mouseButtons: [String: CGMouseButton] = [
    "left": .left,
    "right": .right,
    "center": .center,
]

/// Virtual key codes for named keys. Layout-independent names only: the caller
/// asks for "return", not for the physical key that happens to sit there.
let virtualKeys: [String: CGKeyCode] = [
    "return": 36, "enter": 36, "tab": 48, "space": 49, "escape": 53, "esc": 53,
    "delete": 51, "backspace": 51, "forwarddelete": 117,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26,
    "8": 28, "9": 25,
    "minus": 27, "equal": 24, "comma": 43, "period": 47, "slash": 44,
    "semicolon": 41, "quote": 39, "backslash": 42, "grave": 50,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
]

let modifierFlags: [String: CGEventFlags] = [
    "cmd": .maskCommand, "command": .maskCommand, "meta": .maskCommand,
    "shift": .maskShift,
    "alt": .maskAlternate, "opt": .maskAlternate, "option": .maskAlternate,
    "ctrl": .maskControl, "control": .maskControl,
    "fn": .maskSecondaryFn,
]

func resolveModifiers(_ names: [String]) throws -> (CGEventFlags, [String]) {
    var flags: CGEventFlags = []
    var normalized: [String] = []
    for name in names {
        let key = name.lowercased()
        guard let flag = modifierFlags[key] else {
            throw DriverError(
                code: "unknown_modifier",
                message: "unknown modifier \(name)"
            )
        }
        flags.insert(flag)
        normalized.append(key)
    }
    return (flags, normalized)
}

func mouseEvent(
    _ type: CGEventType,
    point: CGPoint,
    button: CGMouseButton,
    flags: CGEventFlags
) throws -> Int {
    guard let event = CGEvent(
        mouseEventSource: nil,
        mouseType: type,
        mouseCursorPosition: point,
        mouseButton: button
    ) else {
        throw DriverError(code: "mouse_event_failed", message: "cannot create mouse event")
    }
    event.flags = flags
    event.post(tap: .cghidEventTap)
    return 1
}

/// Post a click at `point` with the given button, multi-click count and
/// modifier flags. The click count is attached to both the down and up event so
/// AppKit reports a genuine double/triple click instead of two single clicks.
func performClick(
    at point: PointValue,
    buttonName: String,
    count: Int,
    flags: CGEventFlags
) throws -> Int {
    guard let button = mouseButtons[buttonName] else {
        throw DriverError(code: "unknown_button", message: "unknown button \(buttonName)")
    }
    guard count >= 1 else {
        throw DriverError(code: "invalid_arguments", message: "count must be >= 1")
    }
    let downType: CGEventType =
        button == .left ? .leftMouseDown : (button == .right ? .rightMouseDown : .otherMouseDown)
    let upType: CGEventType =
        button == .left ? .leftMouseUp : (button == .right ? .rightMouseUp : .otherMouseUp)
    let value = CGPoint(x: point.x, y: point.y)

    var posted = try mouseEvent(
        .mouseMoved, point: value, button: button, flags: flags
    )
    for clickIndex in 1...count {
        guard let down = CGEvent(
            mouseEventSource: nil,
            mouseType: downType,
            mouseCursorPosition: value,
            mouseButton: button
        ), let up = CGEvent(
            mouseEventSource: nil,
            mouseType: upType,
            mouseCursorPosition: value,
            mouseButton: button
        ) else {
            throw DriverError(code: "mouse_event_failed", message: "cannot create click event")
        }
        down.flags = flags
        up.flags = flags
        down.setIntegerValueField(.mouseEventClickState, value: Int64(clickIndex))
        up.setIntegerValueField(.mouseEventClickState, value: Int64(clickIndex))
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        posted += 2
        if clickIndex < count {
            // Stay inside the double-click interval the window server expects.
            usleep(40_000)
        }
    }
    return posted
}

/// Describe the element that currently owns keyboard focus.
///
/// Keyboard input has no coordinates, so an operation that types or taps keys
/// only means what it claims if focus is where the caller believes it is. The
/// window server happily routes keystrokes into whatever holds focus, which
/// makes a stale or mis-clicked focus a silent corruption rather than a failure.
func focusedElementInfo(
    _ window: WindowValue
) -> (role: String, identifier: String, title: String)? {
    let application = applicationElement(pid: window.pid)
    guard let focused = copyElementAttribute(
        application,
        kAXFocusedUIElementAttribute as CFString
    ) else {
        return nil
    }
    return (
        role: stringAttribute(focused, kAXRoleAttribute as CFString) ?? "",
        identifier: stringAttribute(focused, kAXIdentifierAttribute as CFString) ?? "",
        title: stringAttribute(focused, kAXTitleAttribute as CFString) ?? ""
    )
}

/// Confirm the application still reports the expected element as focus holder.
///
/// The caller supplies the identity it observed (role, identifier, title)
/// because that is stable across traversals; the chain-derived element id is
/// not, since the popup layers around a search field change the path.
func requireFocus(
    window: WindowValue,
    role expectedRole: String,
    identifier expectedIdentifier: String,
    title expectedTitle: String
) throws -> (role: String, identifier: String, title: String) {
    guard let focus = focusedElementInfo(window) else {
        throw DriverError(
            code: "focus_unavailable",
            message: "cannot read the focused element for window \(window.window_id)"
        )
    }
    // Compare by the same identity the caller observed: role, identifier and
    // title. Position is deliberately excluded because a focused text field
    // reports its own frame, not the observation's.
    guard focus.role == expectedRole,
          focus.identifier == expectedIdentifier,
          focus.title == expectedTitle
    else {
        throw DriverError(
            code: "focus_mismatch",
            message: (
                "focus is on \(focus.role) id=\(focus.identifier) "
                + "title=\(focus.title), expected \(expectedRole) "
                + "id=\(expectedIdentifier) title=\(expectedTitle)"
            )
        )
    }
    return focus
}

/// Post `text` as keyboard input.
///
/// Characters are sent as Unicode payloads on the event rather than as key
/// codes, so layout and IME state cannot turn "文件" into a run of dead keys.
///
/// One event per character, spaced by `interval`, because hosts that route input
/// through a separate process drop characters from a single crowded event.
func performTypeText(_ text: String, flags: CGEventFlags) throws -> Int {
    guard !text.isEmpty else {
        throw DriverError(code: "invalid_arguments", message: "text must not be empty")
    }
    var posted = 0
    for scalar in text.unicodeScalars {
        var unit = UniChar(scalar.value & 0xFFFF)
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)
        else {
            throw DriverError(code: "key_event_failed", message: "cannot create text event")
        }
        down.flags = flags
        up.flags = flags
        down.keyboardSetUnicodeString(stringLength: 1, unicodeString: &unit)
        up.keyboardSetUnicodeString(stringLength: 1, unicodeString: &unit)
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        posted += 2
        usleep(15_000)
    }
    return posted
}

/// Post a named key (or a modifier combination such as `cmd+v`).
func performKeyTap(_ name: String, extraModifiers: [String]) throws -> (Int, String, [String]) {
    let parts = name.lowercased().split(separator: "+").map(String.init)
    var keyName: String?
    var rawModifiers = extraModifiers
    for part in parts {
        if modifierFlags[part] != nil {
            rawModifiers.append(part)
        } else {
            keyName = part
        }
    }
    guard let resolvedKey = keyName else {
        throw DriverError(
            code: "invalid_arguments",
            message: "key tap needs a key name in \(name)"
        )
    }
    guard let code = virtualKeys[resolvedKey] else {
        throw DriverError(code: "unknown_key", message: "unknown key \(resolvedKey)")
    }
    let (flags, normalized) = try resolveModifiers(rawModifiers)
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false)
    else {
        throw DriverError(code: "key_event_failed", message: "cannot create key event")
    }
    down.flags = flags
    up.flags = flags
    down.post(tap: .cghidEventTap)
    usleep(20_000)
    up.post(tap: .cghidEventTap)
    return (2, resolvedKey, normalized)
}

/// Scroll by a wheel delta. Positive `dy` scrolls content up (natural wheel-up).
func performScroll(dx: Double, dy: Double, flags: CGEventFlags) throws -> Int {
    guard let event = CGEvent(
        scrollWheelEvent2Source: nil,
        units: .pixel,
        wheelCount: 2,
        wheel1: Int32(dy),
        wheel2: Int32(dx),
        wheel3: 0
    ) else {
        throw DriverError(code: "scroll_event_failed", message: "cannot create scroll event")
    }
    event.flags = flags
    event.post(tap: .cghidEventTap)
    return 1
}

/// Press at `from`, interpolate to `to`, release. Applications with custom
/// drag handling need intermediate moves, not a two-point jump.
func performDrag(
    from: PointValue,
    to: PointValue,
    buttonName: String,
    steps: Int,
    flags: CGEventFlags
) throws -> Int {
    guard let button = mouseButtons[buttonName] else {
        throw DriverError(code: "unknown_button", message: "unknown button \(buttonName)")
    }
    let downType: CGEventType =
        button == .left ? .leftMouseDown : (button == .right ? .rightMouseDown : .otherMouseDown)
    let dragType: CGEventType =
        button == .left ? .leftMouseDragged : (button == .right ? .rightMouseDragged : .otherMouseDragged)
    let upType: CGEventType =
        button == .left ? .leftMouseUp : (button == .right ? .rightMouseUp : .otherMouseUp)
    let moveCount = max(steps, 1)
    let start = CGPoint(x: from.x, y: from.y)
    let end = CGPoint(x: to.x, y: to.y)

    var posted = try mouseEvent(.mouseMoved, point: start, button: button, flags: flags)
    posted += try mouseEvent(downType, point: start, button: button, flags: flags)
    for step in 1...moveCount {
        let fraction = Double(step) / Double(moveCount)
        let point = CGPoint(
            x: start.x + (end.x - start.x) * fraction,
            y: start.y + (end.y - start.y) * fraction
        )
        posted += try mouseEvent(dragType, point: point, button: button, flags: flags)
        usleep(12_000)
    }
    posted += try mouseEvent(upType, point: end, button: button, flags: flags)
    return posted
}

/// True when the window's owning application is the frontmost application.
///
/// Synthetic keyboard events are delivered to the frontmost application, not to
/// the application that holds accessibility focus. A focus assertion alone
/// therefore proves nothing about where a keystroke lands: measured, WeChat
/// reported the search field as focused while the terminal was frontmost, and
/// every keystroke went to the terminal.
func isFrontmost(_ window: WindowValue) -> Bool {
    NSWorkspace.shared.frontmostApplication?.processIdentifier == window.pid
}

/// Make the window's application frontmost and wait until it actually is.
///
/// Raising the window is not instantaneous, and activation also resets the
/// application's first responder, so the focus assertion must run *after* this
/// settles rather than before.
func requireFrontmost(_ window: WindowValue, timeout: Double = 2.0) throws {
    if isFrontmost(window) { return }
    try activateApplication(window)
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if isFrontmost(window) { return }
        usleep(50_000)
    }
    throw DriverError(
        code: "window_not_frontmost",
        message: (
            "window \(window.window_id) (\(window.application_name)) is not "
            + "frontmost; keyboard input would go to "
            + (NSWorkspace.shared.frontmostApplication?.localizedName ?? "another app")
        )
    )
}

/// Re-assert focus, tolerating the short window in which an application has not
/// yet moved focus after the click that requested it.
///
/// Focus transfer is asynchronous: the click is posted, and the host application
/// updates its focus holder on its own run loop. Checking once immediately after
/// the click races that update and reports a false mismatch, which is exactly
/// the failure mode this helper exists to remove.
func requireFocusSettled(
    window: WindowValue,
    role: String,
    identifier: String,
    title: String,
    timeout: Double = 1.0
) throws -> (role: String, identifier: String, title: String) {
    let deadline = Date().addingTimeInterval(timeout)
    var lastError: DriverError?
    repeat {
        do {
            return try requireFocus(
                window: window,
                role: role,
                identifier: identifier,
                title: title
            )
        } catch let error as DriverError {
            lastError = error
            // A mismatch may still settle; a missing focus read will not.
            if error.code != "focus_mismatch" { throw error }
            usleep(60_000)
        }
    } while Date() < deadline
    throw lastError ?? DriverError(
        code: "focus_mismatch",
        message: "focus did not settle on the expected element"
    )
}

/// Verify the focus a click was supposed to produce, when the caller asked for
/// that check. Asserting is opt-in because a click may legitimately land on a
/// control that does not take focus; asserting is what turns "the click was
/// posted" into "the click did what it claimed".
func assertFocusAfterClick(
    request: Request,
    window: WindowValue
) throws -> String? {
    guard let expectedRole = request.expect_role else { return nil }
    let focus = try requireFocusSettled(
        window: window,
        role: expectedRole,
        identifier: request.expect_identifier ?? "",
        title: request.expect_title ?? ""
    )
    return focus.identifier
}

/// Bring the owning application forward and raise the target window.
///
/// A synthetic click on an inactive application is consumed as the activating
/// click and never reaches the control. Activating first makes a coordinate
/// click land on the intended element instead of being swallowed.
func activateApplication(_ window: WindowValue) throws {
    if let running = NSRunningApplication(processIdentifier: window.pid) {
        if !running.isActive {
            running.activate(options: [.activateAllWindows])
        }
    }
    let element = selectAXWindow(window)
    var value: CFTypeRef?
    if AXUIElementCopyAttributeValue(
        element,
        kAXRoleAttribute as CFString,
        &value
    ) == .success,
       let role = value as? String,
       role == (kAXWindowRole as String) {
        _ = AXUIElementPerformAction(element, kAXRaiseAction as CFString)
    }
    // Give the window server a moment to process the activation before the
    // synthetic click is posted.
    usleep(250_000)
}

func hitTest(
    _ window: WindowValue,
    root: AXUIElement,
    point: PointValue
) throws -> HitTestResult {
    let application = applicationElement(pid: window.pid)
    var element: AXUIElement?
    let status = AXUIElementCopyElementAtPosition(
        application,
        Float(point.x),
        Float(point.y),
        &element
    )
    guard status == .success, let hit = element else {
        throw DriverError(
            code: "hit_test_failed",
            message: "no accessibility element at \(point.x),\(point.y)"
        )
    }
    let position = pointAttribute(hit, kAXPositionAttribute as CFString)
    let size = sizeAttribute(hit, kAXSizeAttribute as CFString)
    let chain = positionChain(hit, root: root)
    return HitTestResult(
        point: point,
        element_id: elementIdentifier(hit, chain: chain),
        element_path: encodeChain(chain),
        role: stringAttribute(hit, kAXRoleAttribute as CFString) ?? "AXUnknown",
        title: stringAttribute(hit, kAXTitleAttribute as CFString),
        description: stringAttribute(hit, kAXDescriptionAttribute as CFString),
        value: stringAttribute(hit, kAXValueAttribute as CFString),
        position: position.map { PointValue(x: $0.x, y: $0.y) },
        size: size.map { SizeValue(width: $0.width, height: $0.height) },
        child_count: elementChildren(hit).count,
        parent_chain: ancestorChain(hit, root: root),
        actions: elementActions(hit)
    )
}

func observe(_ identifier: String, screenshotPath: String) async throws -> ObserveResult {
    let started = Date()
    let selected = try selectWindow(identifier)
    let selectedAt = Date()
    let root = selectAXWindow(selected)
    let accessibility = enableWebAccessibility(pid: selected.pid)
    var elements: [ElementValue] = []
    let truncated = walkElement(
        root,
        root: root,
        chain: [],
        parentID: nil,
        depth: 0,
        maximumDepth: 80,
        maximumElements: 20_000,
        output: &elements
    )
    let walkedAt = Date()
    let (width, height, scale) = try await screenshot(selected, outputPath: screenshotPath)
    let capturedAt = Date()
    let visualDigest = try fileDigest(screenshotPath)
    let digestedAt = Date()
    let payload = try jsonData(selected) + jsonData(elements) + Data(visualDigest.utf8)
    let revision = "sha256:" + sha256(payload)
    return ObserveResult(
        window: selected,
        revision: revision,
        visual_digest: visualDigest,
        elements: elements,
        truncated: truncated,
        screenshot_path: screenshotPath,
        screenshot_width: width,
        screenshot_height: height,
        screenshot_scale: scale,
        accessibility: accessibility,
        timings_ms: [
            "select_window": selectedAt.timeIntervalSince(started) * 1000,
            "ax_walk": walkedAt.timeIntervalSince(selectedAt) * 1000,
            "screenshot": capturedAt.timeIntervalSince(walkedAt) * 1000,
            "digest": digestedAt.timeIntervalSince(capturedAt) * 1000,
            "total": digestedAt.timeIntervalSince(started) * 1000,
        ]
    )
}

func sha256(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

/// Minimal JSON request decoder for the persistent socket mode.
struct Request: Decodable {
    let command: String
    var window: String?
    var output: String?
    var element: String?
    var value: String?
    var x: Double?
    var y: Double?
    var to_x: Double?
    var to_y: Double?
    var text: String?
    var key: String?
    var button: String?
    var count: Int?
    var steps: Int?
    var dx: Double?
    var dy: Double?
    var modifiers: [String]?
    var duration: Double?
    /// Focus assertion for keyboard operations: the role/identifier/title the
    /// caller observed for the element that must hold focus.
    var expect_role: String?
    var expect_identifier: String?
    var expect_title: String?
    /// `mouse-move`/`click-point` need an activation guard by default because a
    /// synthetic click on an unfocused app is swallowed. Callers driving an
    /// in-app transient like a search suggestion list must opt out: the
    /// activation reorders windows and dismisses the popup.
    var activate: Bool?
}

struct WindowsResponse: Codable {
    let windows: [WindowValue]
}

struct PointWindowResult: Codable {
    let point: PointValue
    let window_id: UInt32
    let pid: Int32
    let application_name: String
    let title: String
    let layer: Int
}

/// Commands the shared dispatcher accepts. `list-windows`, `observe` and
/// `serve` are handled separately because they are not request-shaped actions.
let requestCommands: Set<String> = [
    "click-element", "click-point", "set-value", "hit-test", "window-at-point",
    "mouse-move", "drag", "scroll", "type-text", "key-tap",
]

func isRequestCommand(_ name: String) -> Bool {
    requestCommands.contains(name)
}

/// Topmost on-screen window containing the point, in CGWindowList order.
func windowAtPoint(_ point: PointValue) -> PointWindowResult? {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        as? [[String: Any]]
    else {
        return nil
    }
    for item in raw {
        guard let number = item[kCGWindowNumber as String] as? NSNumber,
              let pid = item[kCGWindowOwnerPID as String] as? NSNumber,
              let bounds = item[kCGWindowBounds as String] as? [String: Any]
        else {
            continue
        }
        let x = (bounds["X"] as? NSNumber)?.doubleValue ?? 0
        let y = (bounds["Y"] as? NSNumber)?.doubleValue ?? 0
        let width = (bounds["Width"] as? NSNumber)?.doubleValue ?? 0
        let height = (bounds["Height"] as? NSNumber)?.doubleValue ?? 0
        guard point.x >= x, point.x <= x + width,
              point.y >= y, point.y <= y + height
        else {
            continue
        }
        let running = NSRunningApplication(processIdentifier: pid.int32Value)
        return PointWindowResult(
            point: point,
            window_id: number.uint32Value,
            pid: pid.int32Value,
            application_name: running?.localizedName ?? "",
            title: item[kCGWindowName as String] as? String ?? "",
            layer: (item[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0
        )
    }
    return nil
}

func handleRequest(_ request: Request) async -> [String: Any] {
    do {
        switch request.command {
        case "list-windows":
            return try jsonObject(WindowsResponse(windows: windowInfo()))
        case "observe":
            guard let window = request.window, let output = request.output else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "observe requires window and output"
                )
            }
            return try jsonObject(try await observe(window, screenshotPath: output))
        case "click-element":
            guard let window = request.window, let element = request.element else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "click-element requires window and element"
                )
            }
            let selected = try selectWindow(window)
            let root = selectAXWindow(selected)
            guard let target = findElement(
                root,
                root: root,
                chain: [],
                identifier: element
            ) else {
                throw DriverError(
                    code: "element_not_found",
                    message: "no AX element matched \(element)"
                )
            }
            try performAXAction(target, action: kAXPressAction as String)
            return try jsonObject(
                ActResult(action: "press", element_id: element, point: nil, performed: true)
            )
        case "click-point":
            guard let window = request.window,
                  let x = request.x,
                  let y = request.y
            else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "click-point requires window, x, and y"
                )
            }
            let selected = try selectWindow(window)
            let point = PointValue(x: x, y: y)
            try requirePointInside(point, window: selected)
            let buttonName = request.button ?? "left"
            let count = request.count ?? 1
            let (flags, _) = try resolveModifiers(request.modifiers ?? [])
            if request.activate ?? true {
                try activateApplication(selected)
                try performPointClick(point)
                let focus = try assertFocusAfterClick(
                    request: request, window: selected
                )
                return try jsonObject(
                    InputResult(
                        action: "click", point: point, from: nil, to: nil,
                        button: buttonName, count: count, text: nil, key: nil,
                        modifiers: nil, events: 3, performed: true,
                        focus: focus
                    )
                )
            }
            let events = try performClick(
                at: point, buttonName: buttonName, count: count, flags: flags
            )
            let focus = try assertFocusAfterClick(
                request: request, window: selected
            )
            return try jsonObject(
                InputResult(
                    action: "click", point: point, from: nil, to: nil,
                    button: buttonName, count: count, text: nil, key: nil,
                    modifiers: nil, events: events, performed: true,
                    focus: focus
                )
            )
        case "mouse-move":
            guard let window = request.window, let x = request.x, let y = request.y else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "mouse-move requires window, x, and y"
                )
            }
            let selected = try selectWindow(window)
            let point = PointValue(x: x, y: y)
            try requirePointInside(point, window: selected)
            if request.activate ?? false {
                try activateApplication(selected)
            }
            let buttonName = request.button ?? "left"
            guard let button = mouseButtons[buttonName] else {
                throw DriverError(code: "unknown_button", message: "unknown button \(buttonName)")
            }
            let (flags, _) = try resolveModifiers(request.modifiers ?? [])
            let events = try mouseEvent(
                .mouseMoved,
                point: CGPoint(x: point.x, y: point.y),
                button: button,
                flags: flags
            )
            return try jsonObject(
                InputResult(
                    action: "mouse_move", point: point, from: nil, to: nil,
                    button: buttonName, count: nil, text: nil, key: nil,
                    modifiers: nil, events: events, performed: true
                )
            )
        case "drag":
            guard let window = request.window,
                  let x = request.x, let y = request.y,
                  let toX = request.to_x, let toY = request.to_y
            else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "drag requires window, x, y, to_x, and to_y"
                )
            }
            let selected = try selectWindow(window)
            let from = PointValue(x: x, y: y)
            let to = PointValue(x: toX, y: toY)
            try requirePointInside(from, window: selected)
            try requirePointInside(to, window: selected)
            if request.activate ?? true {
                try activateApplication(selected)
            }
            let buttonName = request.button ?? "left"
            let (flags, _) = try resolveModifiers(request.modifiers ?? [])
            let events = try performDrag(
                from: from, to: to, buttonName: buttonName,
                steps: request.steps ?? 12, flags: flags
            )
            return try jsonObject(
                InputResult(
                    action: "drag", point: nil, from: from, to: to,
                    button: buttonName, count: nil, text: nil, key: nil,
                    modifiers: nil, events: events, performed: true
                )
            )
        case "scroll":
            guard let window = request.window,
                  let x = request.x, let y = request.y
            else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "scroll requires window, x, and y"
                )
            }
            let selected = try selectWindow(window)
            let point = PointValue(x: x, y: y)
            try requirePointInside(point, window: selected)
            if request.activate ?? false {
                try activateApplication(selected)
            }
            // Park the cursor on the scroll target first: wheel events go to the
            // view under the pointer, not to the focused window.
            _ = try mouseEvent(
                .mouseMoved,
                point: CGPoint(x: point.x, y: point.y),
                button: .left,
                flags: []
            )
            let (flags, _) = try resolveModifiers(request.modifiers ?? [])
            let events = try performScroll(
                dx: request.dx ?? 0, dy: request.dy ?? 0, flags: flags
            )
            return try jsonObject(
                InputResult(
                    action: "scroll", point: point, from: nil, to: nil,
                    button: nil, count: nil, text: nil, key: nil,
                    modifiers: nil, events: events, performed: true
                )
            )
        case "type-text":
            guard let text = request.text else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "type-text requires text"
                )
            }
            // Typing has no coordinates. Without a focus assertion the
            // keystrokes land in whatever held focus, which is how a mis-click
            // turns into silent corruption instead of an error.
            guard let target = request.window,
                  let expectedRole = request.expect_role,
                  let expectedIdentifier = request.expect_identifier
            else {
                throw DriverError(
                    code: "focus_target_missing",
                    message: (
                        "type-text requires window, expect_role and "
                        + "expect_identifier so focus can be verified"
                    )
                )
            }
            let selected = try selectWindow(target)
            // Activation both grants frontmost status and resets the first
            // responder, so it must happen before the focus assertion, not after.
            try requireFrontmost(selected)
            let focus = try requireFocusSettled(
                window: selected,
                role: expectedRole,
                identifier: expectedIdentifier,
                title: request.expect_title ?? ""
            )
            let (flags, _) = try resolveModifiers(request.modifiers ?? [])
            let events = try performTypeText(text, flags: flags)
            return try jsonObject(
                InputResult(
                    action: "type_text", point: nil, from: nil, to: nil,
                    button: nil, count: nil, text: text, key: nil,
                    modifiers: nil, events: events, performed: true,
                    focus: focus.identifier
                )
            )
        case "key-tap":
            guard let key = request.key else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "key-tap requires key"
                )
            }
            // A key tap is only meaningful against an asserted focus holder;
            // see the type-text case.
            guard let target = request.window,
                  let expectedRole = request.expect_role,
                  let expectedIdentifier = request.expect_identifier
            else {
                throw DriverError(
                    code: "focus_target_missing",
                    message: (
                        "key-tap requires window, expect_role and "
                        + "expect_identifier so focus can be verified"
                    )
                )
            }
            let selected = try selectWindow(target)
            // See type-text: frontmost first, then assert focus.
            try requireFrontmost(selected)
            let focus = try requireFocusSettled(
                window: selected,
                role: expectedRole,
                identifier: expectedIdentifier,
                title: request.expect_title ?? ""
            )
            let (events, resolved, normalized) = try performKeyTap(
                key, extraModifiers: request.modifiers ?? []
            )
            return try jsonObject(
                InputResult(
                    action: "key_tap", point: nil, from: nil, to: nil,
                    button: nil, count: nil, text: nil, key: resolved,
                    modifiers: normalized, events: events, performed: true,
                    focus: focus.identifier
                )
            )
        case "set-value":
            guard let window = request.window,
                  let element = request.element,
                  let value = request.value
            else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "set-value requires window, element, and value"
                )
            }
            let selected = try selectWindow(window)
            let root = selectAXWindow(selected)
            guard let target = findElement(
                root,
                root: root,
                chain: [],
                identifier: element
            ) else {
                throw DriverError(
                    code: "element_not_found",
                    message: "no AX element matched \(element)"
                )
            }
            let status = AXUIElementSetAttributeValue(
                target,
                kAXValueAttribute as CFString,
                value as CFTypeRef
            )
            if status != .success {
                throw DriverError(
                    code: "ax_set_value_failed",
                    message: "AX set value failed with status \(status.rawValue)"
                )
            }
            return try jsonObject(
                ActResult(
                    action: "set_value",
                    element_id: element,
                    point: nil,
                    performed: true
                )
            )
        case "hit-test":
            guard let window = request.window,
                  let x = request.x,
                  let y = request.y
            else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "hit-test requires window, x, and y"
                )
            }
            let selected = try selectWindow(window)
            return try jsonObject(
                try hitTest(
                    selected,
                    root: selectAXWindow(selected),
                    point: PointValue(x: x, y: y)
                )
            )
        case "window-at-point":
            guard let x = request.x, let y = request.y else {
                throw DriverError(
                    code: "invalid_arguments",
                    message: "window-at-point requires x and y"
                )
            }
            guard let found = windowAtPoint(PointValue(x: x, y: y)) else {
                throw DriverError(
                    code: "window_not_found",
                    message: "no on-screen window contains \(x),\(y)"
                )
            }
            return try jsonObject(found)
        default:
            throw DriverError(
                code: "unknown_command",
                message: "unknown socket command \(request.command)"
            )
        }
    } catch let error as DriverError {
        return ["error": ["code": error.code, "message": error.message]]
    } catch {
        return ["error": ["code": "driver_error", "message": String(describing: error)]]
    }
}

func jsonObject<T: Encodable>(_ value: T) throws -> [String: Any] {
    let data = try jsonData(value)
    guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw DriverError(code: "encode_failed", message: "cannot encode response")
    }
    return object
}

/// Emit a response dictionary produced by `handleRequest`.
func writeObject(_ object: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))
}

/// Split a comma-separated CLI list such as `--modifiers cmd,shift`.
func argumentList(_ name: String) -> [String] {
    guard let raw = argument(name) else { return [] }
    return raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }
}

func serveSocket(_ path: String) async throws {
    let socketPath = path as NSString
    try? FileManager.default.removeItem(atPath: path)
    let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
    guard descriptor >= 0 else {
        throw DriverError(code: "socket_failed", message: "cannot create socket")
    }
    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    guard path.utf8.count < MemoryLayout.size(
        ofValue: address.sun_path
    ) else {
        throw DriverError(code: "socket_path_too_long", message: path)
    }
    withUnsafeMutablePointer(to: &address.sun_path) { pointer in
        pointer.withMemoryRebound(to: CChar.self, capacity: 104) { destination in
            _ = strcpy(destination, socketPath.utf8String!)
        }
    }
    let bound = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }
    guard bound == 0 else {
        throw DriverError(
            code: "socket_bind_failed",
            message: "cannot bind \(path): errno \(errno)"
        )
    }
    guard listen(descriptor, 16) == 0 else {
        throw DriverError(code: "socket_listen_failed", message: "errno \(errno)")
    }
    FileHandle.standardError.write(Data("macjev-computer-driver listening\n".utf8))
    while true {
        let client = accept(descriptor, nil, nil)
        if client < 0 {
            continue
        }
        // Serialize on the accept thread: AX calls are significantly cheaper
        // on the main run loop than on a detached cooperative thread.
        await serveClient(client)
    }
}

func serveClient(_ descriptor: Int32) async {
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    while let line = readLine(from: handle) {
        guard let data = line.data(using: .utf8),
              let request = try? JSONDecoder().decode(Request.self, from: data)
        else {
            let payload = try? JSONSerialization.data(
                withJSONObject: [
                    "error": ["code": "invalid_json", "message": "bad request"],
                ]
            )
            handle.write((payload ?? Data()) + Data([0x0a]))
            continue
        }
        let response = await handleRequest(request)
        guard let payload = try? JSONSerialization.data(
            withJSONObject: response,
            options: [.sortedKeys]
        ) else {
            continue
        }
        handle.write(payload + Data([0x0a]))
    }
}

func readLine(from handle: FileHandle) -> String? {
    var buffer = Data()
    while true {
        let byte = handle.readData(ofLength: 1)
        if byte.isEmpty {
            return buffer.isEmpty ? nil : String(decoding: buffer, as: UTF8.self)
        }
        if byte[0] == 0x0a {
            return String(decoding: buffer, as: UTF8.self)
        }
        buffer.append(byte)
    }
}

func fileDigest(_ path: String) throws -> String {
    guard let data = FileManager.default.contents(atPath: path) else {
        throw DriverError(
            code: "screenshot_missing",
            message: "cannot read screenshot at \(path)"
        )
    }
    return "sha256:" + sha256(data)
}

@main
struct Main {
    static func main() async {
        do {
            let command = CommandLine.arguments.dropFirst().first ?? "help"
            switch command {
            case "list-windows":
                try writeJSON(["windows": windowInfo()])
            case "serve":
                guard let path = argument("--socket") else {
                    throw DriverError(
                        code: "invalid_arguments",
                        message: "serve requires --socket"
                    )
                }
                try await serveSocket(path)
            case "observe":
                guard let target = argument("--window"),
                      let output = argument("--output")
                else {
                    throw DriverError(
                        code: "invalid_arguments",
                        message: "observe requires --window and --output"
                    )
                }
                try writeJSON(try await observe(target, screenshotPath: output))
            default:
                // Every remaining command is a request-shaped action. Sharing
                // one dispatcher keeps `driver <cmd> --flag` and the socket
                // protocol identical instead of drifting apart over time.
                let request = Request(
                    command: command,
                    window: argument("--window"),
                    output: nil,
                    element: argument("--element"),
                    value: argument("--value"),
                    x: argument("--x").flatMap(Double.init),
                    y: argument("--y").flatMap(Double.init),
                    to_x: argument("--to-x").flatMap(Double.init),
                    to_y: argument("--to-y").flatMap(Double.init),
                    text: argument("--text"),
                    key: argument("--key"),
                    button: argument("--button"),
                    count: argument("--count").flatMap(Int.init),
                    steps: argument("--steps").flatMap(Int.init),
                    dx: argument("--dx").flatMap(Double.init),
                    dy: argument("--dy").flatMap(Double.init),
                    modifiers: argumentList("--modifiers"),
                    duration: argument("--duration").flatMap(Double.init),
                    expect_role: argument("--expect-role"),
                    expect_identifier: argument("--expect-identifier"),
                    expect_title: argument("--expect-title"),
                    activate: argument("--activate").flatMap(Bool.init)
                )
                guard isRequestCommand(command) else {
                    throw DriverError(
                        code: "unknown_command",
                        message: "unknown command \(command)"
                    )
                }
                let object = await handleRequest(request)
                if let error = object["error"] as? [String: Any],
                   let code = error["code"] as? String,
                   let message = error["message"] as? String {
                    fail(code, message)
                }
                try writeObject(object)
            }
        } catch let error as DriverError {
            fail(error.code, error.message)
        } catch {
            fail("driver_error", String(describing: error))
        }
    }
}

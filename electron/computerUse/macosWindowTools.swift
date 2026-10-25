import Foundation
import CoreGraphics
import ApplicationServices

// ADR 0081 P1: macOS 只读工具。枚举窗口(CGWindowList)、AX 可访问性树。
// 不注入任何输入;需要哪些系统权限由系统弹窗/设置决定,这里不静默降级。

struct WindowJSON {
    static func write(_ value: Any) {
        guard let data = try? JSONSerialization.data(withJSONObject: value),
              let text = String(data: data, encoding: .utf8) else {
            FileHandle.standardError.write(Data("json encoding failed\n".utf8))
            exit(2)
        }
        print(text)
    }
}

func listWindows() -> [[String: Any]] {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
        return []
    }
    var result: [[String: Any]] = []
    for item in raw {
        guard let number = item[kCGWindowNumber as String] as? NSNumber else { continue }
        let bounds = item[kCGWindowBounds as String] as? [String: NSNumber] ?? [:]
        result.append([
            "id": number.uint32Value,
            "owner": item[kCGWindowOwnerName as String] as? String ?? "",
            "pid": (item[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value ?? 0,
            "title": item[kCGWindowName as String] as? String ?? "",
            "x": bounds["X"]?.doubleValue ?? 0,
            "y": bounds["Y"]?.doubleValue ?? 0,
            "width": bounds["Width"]?.doubleValue ?? 0,
            "height": bounds["Height"]?.doubleValue ?? 0,
            "layer": (item[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0,
            "alpha": (item[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1,
            "onscreen": (item[kCGWindowIsOnscreen as String] as? NSNumber)?.boolValue ?? false,
        ])
    }
    return result
}


func stringAttribute(_ element: AXUIElement, _ name: String) -> String {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else { return "" }
    return value as? String ?? ""
}

func frameAttributes(_ element: AXUIElement) -> [String: Double] {
    var frame: [String: Double] = [:]
    var position: CFTypeRef?
    if AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success, let value = position {
        var point = CGPoint.zero
        if AXValueGetValue(value as! AXValue, .cgPoint, &point) {
            frame["x"] = point.x
            frame["y"] = point.y
        }
    }
    var size: CFTypeRef?
    if AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success, let value = size {
        var sizeValue = CGSize.zero
        if AXValueGetValue(value as! AXValue, .cgSize, &sizeValue) {
            frame["width"] = sizeValue.width
            frame["height"] = sizeValue.height
        }
    }
    return frame
}

func accessibilityTree(_ pid: Int32) -> [String: Any] {
    let application = AXUIElementCreateApplication(pid)
    let snapshot = UUID().uuidString
    var index = 0
    var elements: [[String: Any]] = []
    func walk(_ element: AXUIElement, depth: Int) {
        if depth > 10 || elements.count >= 400 { return }
        let identifier = "\(snapshot):\(index)"
        index += 1
        var node: [String: Any] = [
            "id": identifier,
            "role": stringAttribute(element, kAXRoleAttribute),
            "title": stringAttribute(element, kAXTitleAttribute),
        ]
        let frame = frameAttributes(element)
        if !frame.isEmpty { node["frame"] = frame }
        elements.append(node)
        var children: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &children) == .success,
              let list = children as? [AXUIElement] else { return }
        for child in list.prefix(80) { walk(child, depth: depth + 1) }
    }
    var rootChildren: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(application, kAXChildrenAttribute as CFString, &rootChildren)
    if result != .success {
        return ["error": ["code": result.rawValue, "message": "AXUIElementCopyAttributeValue failed: \(result)"]]
    }
    walk(application, depth: 0)
    return ["snapshot_id": snapshot, "elements": elements]
}

func permissionStatus() -> [String: Bool] {
    return [
        "accessibility": AXIsProcessTrusted(),
        "screen": CGPreflightScreenCaptureAccess(),
    ]
}

/// 只有用户点了「向系统申请」才走到这里;状态查询绝不触发系统弹窗。
func requestPermission(_ kind: String) -> Bool {
    switch kind {
    case "accessibility":
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    case "screen":
        return CGRequestScreenCaptureAccess()
    default:
        FileHandle.standardError.write(Data("unknown permission: \(kind)\n".utf8))
        exit(2)
    }
}

let arguments = CommandLine.arguments
if arguments.count < 2 {
    FileHandle.standardError.write(Data("usage: macos-window-tools windows | permissions | request-permission <accessibility|screen> | ax <pid>\n".utf8))
    exit(2)
}

switch arguments[1] {
case "windows":
    WindowJSON.write(listWindows())
case "permissions":
    WindowJSON.write(permissionStatus())
case "request-permission":
    guard arguments.count >= 3 else {
        FileHandle.standardError.write(Data("request-permission needs accessibility or screen\n".utf8))
        exit(2)
    }
    WindowJSON.write(["granted": requestPermission(arguments[2])])
case "ax":
    guard arguments.count >= 3, let pid = Int32(arguments[2]) else {
        FileHandle.standardError.write(Data("ax needs a numeric pid\n".utf8))
        exit(2)
    }
    WindowJSON.write(accessibilityTree(pid))
default:
    FileHandle.standardError.write(Data("unknown subcommand: \(arguments[1])\n".utf8))
    exit(2)
}

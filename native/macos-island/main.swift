import AppKit
import Foundation

private let decoder = JSONDecoder()

if CommandLine.arguments.contains("--version") {
    print("mosael-island 1")
    exit(0)
}

final class IslandAppDelegate: NSObject, NSApplicationDelegate {
    private let controller = IslandPanelController()

    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let state = try? decoder.decode(IslandState.self, from: data) else { continue }
                DispatchQueue.main.async { self?.controller.apply(state.activities) }
            }
            DispatchQueue.main.async { NSApplication.shared.terminate(nil) }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = IslandAppDelegate()
app.delegate = delegate
app.run()
